# Hybrid Trainer Redis Write Classification

| line | classification | text |
|---:|---|---|
| 145 | read_only | import redis  # needed for redis.exceptions.* in timeout-safe code paths |
| 375 | read_only | # Enable debug mode for SubprocVecEnv workers to bypass Redis |
| 386 | read_only | # Stagger worker startup slightly to avoid Redis/socket "thundering herd" |
| 407 | read_only | # Add worker-specific Redis timeout protection |
| 619 | write_metric | ExecutionEventPublisher, |
| 633 | write_metric | ExecutionEventPublisher = None |
| 993 | read_only | from utils.redis_client import get_redis |
| 1148 | read_only | return float(tf_map.get(tf, MIN_TRADING_CONFIDENCE)) |
| 1155 | read_only | # Symbols can be updated via Redis without restarting the trainer. |
| 1159 | read_only | """Get active symbols from Redis (dynamic) or config.py (fallback).""" |
| 1174 | read_only | from utils.redis_client import get_redis |
| 1200 | read_only | def safe_redis_operation(redis_client, operation, *args, timeout=1.0, default=None, **kwargs): |
| 1202 | read_only | Execute Redis operation with timeout protection to prevent hangs. |
| 1205 | read_only | redis_client: Redis client instance |
| 1206 | read_only | operation: Redis method name (e.g., 'get', 'hgetall') |
| 1207 | read_only | *args: Arguments for Redis operation |
| 1210 | read_only | **kwargs: Keyword arguments for Redis operation |
| 1213 | read_only | Result of Redis operation or default if timeout |
| 1217 | read_only | if redis_client is None: |
| 1222 | read_only | func = getattr(redis_client, operation) |
| 1227 | read_only | logger.warning(f"⚠️ Redis {operation}() timed out after {timeout}s - using default") |
| 1230 | read_only | logger.warning(f"⚠️ Redis {operation}() failed: {e} - using default") |
| 1245 | read_only | def target(): |
| 1264 | read_only | raise exception_queue.get() |
| 1268 | read_only | return result_queue.get() |
| 1327 | read_only | def _lookup_natr_atr_pct(redis_client, symbol: str) -> float: |
| 1331 | read_only | if not redis_client or not symbol: |
| 1335 | read_only | uf = redis_client.hgetall(f"unified_features:{symbol}:5m") or {} |
| 1346 | read_only | v = float(uf.get(k, 0) or 0) |
| 1354 | read_only | def _compute_price_target( |
| 1384 | read_only | }.get(str(timeframe), 1.0) |
| 1396 | read_only | predicted_return = payload.get("predicted_return") |
| 1408 | read_only | ppo_v = payload.get("ppo_value") |
| 1409 | read_only | masa_v = payload.get("masa_value") |
| 1453 | read_only | "_trainer", "trainer", "_signal_redis", "_redis", "redis", |
| 1469 | read_only | _thread.lock objects, Redis connections, and any other runtime-added attrs |
| 1526 | write_signal | # Initialize Redis connection for signal publishing |
| 1528 | read_only | from utils.redis_client import get_redis |
| 1529 | read_only | self._signal_redis = get_redis() |
| 1530 | read_only | if self._signal_redis: |
| 1531 | read_only | self._signal_redis.ping() |
| 1532 | write_signal | logger.info("🔗 GPUForcedPPO: Redis connection initialized for signal publishing") |
| 1534 | read_only | logger.warning("⚠️ GPUForcedPPO: Redis client returned None") |
| 1536 | read_only | logger.warning(f"⚠️ GPUForcedPPO: Could not initialize Redis: {e}") |
| 1537 | read_only | self._signal_redis = None |
| 1548 | read_only | redis_client=self._signal_redis, |
| 1783 | write_metric | """Mirror failing publishes into debug stream for post-mortem analysis.""" |
| 1791 | write_signal | self._signal_redis.xadd( |
| 1794 | read_only | maxlen=5000, |
| 1798 | write_signal | logger.debug(f"[PUBLISH-DEBUG] failed to emit debug signal: {debug_err}") |
| 1838 | read_only | action_name = payload.get('action_name') or payload.get('predicted_action') |
| 1849 | read_only | action_space = payload.get('action_space', '').lower() |
| 1866 | read_only | return trade_map.get(action_idx, 'HOLD') |
| 1937 | read_only | bias = tf_map.get(str(TF_BIAS_TF), {"dir": "FLAT", "conf": 0.0}) |
| 1938 | read_only | confirm = tf_map.get(str(TF_CONFIRM_TF), {"dir": "FLAT", "conf": 0.0}) |
| 1939 | read_only | trigger = tf_map.get(str(TF_TRIGGER_TF), {"dir": "FLAT", "conf": 0.0}) |
| 1942 | read_only | bias.get("dir") == desired_dir and |
| 1943 | read_only | confirm.get("dir") == desired_dir and |
| 1944 | read_only | trigger.get("dir") == desired_dir |
| 1954 | read_only | hist = list(getattr(self, "confidence_history", {}).get(f"{symbol}:{tf}", [])) |
| 1983 | read_only | r = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 1985 | read_only | micro_note = "micro:no_redis" |
| 1988 | read_only | raw = r.hgetall(msnap_key) or {} |
| 1993 | read_only | v = raw.get(k) or raw.get(k.encode()) |
| 2116 | read_only | # HybridTrainer uses self.redis, GPUForcedPPO uses self._signal_redis |
| 2117 | read_only | redis = getattr(self, 'redis', None) or getattr(self, '_signal_redis', None) |
| 2118 | read_only | if not redis: |
| 2122 | read_only | state = redis.get(key) |
| 2135 | read_only | # HybridTrainer uses self.redis, GPUForcedPPO uses self._signal_redis |
| 2136 | read_only | redis = getattr(self, 'redis', None) or getattr(self, '_signal_redis', None) |
| 2137 | read_only | if not redis: |
| 2138 | read_only | logger.warning(f"[HEDGE_BUILD] No Redis client for {symbol}") |
| 2150 | read_only | redis.setex(key, HEDGE_BUILD_TTL_SECONDS, json.dumps(state)) |
| 2158 | read_only | # HybridTrainer uses self.redis, GPUForcedPPO uses self._signal_redis |
| 2159 | read_only | redis = getattr(self, 'redis', None) or getattr(self, '_signal_redis', None) |
| 2160 | read_only | if not redis: |
| 2164 | write_metric | redis.delete(key) |
| 2172 | read_only | # HybridTrainer uses self.redis, GPUForcedPPO uses self._signal_redis |
| 2173 | read_only | redis = getattr(self, 'redis', None) or getattr(self, '_signal_redis', None) |
| 2174 | read_only | if not redis: |
| 2175 | read_only | # Try config.redis_client as fallback |
| 2176 | read_only | redis = getattr(self.config, 'redis_client', None) if hasattr(self, 'config') else None |
| 2178 | read_only | if not redis: |
| 2179 | read_only | logger.info("[HEDGE_BUILD] No Redis client available for feedback poll") |
| 2187 | read_only | entries = redis.xread({stream_key: last_id}, count=50, block=0) |
| 2204 | read_only | raw_data = data.get(b'data') or data.get('data') or '{}' |
| 2208 | read_only | event_type = payload.get('event_type') |
| 2210 | read_only | symbol = payload.get('symbol') |
| 2211 | read_only | side = payload.get('side') |
| 2212 | read_only | account = payload.get('account_id', payload.get('account', 'unknown')) |
| 2213 | read_only | pnl = payload.get('pnl', 0) |
| 2241 | read_only | action_name = str(payload.get('action_name', '') or payload.get('action', '')).upper() |
| 2246 | write_metric | # If the symbol is flat (per trader-published positions), downgrade to a normal OPEN_*. |
| 2262 | read_only | acct = payload.get("account_id") or payload.get("account") or payload.get("target_account_id") |
| 2270 | read_only | p = tp.get(k) or {} |
| 2272 | read_only | return abs(float(p.get("size", 0) or 0.0)) > 0.0 |
| 2323 | write_checkpoint_metadata | # Prefer trader-published positions scoped to payload's account_id. |
| 2326 | read_only | acct = payload.get("account_id") or payload.get("account") or payload.get("target_account_id") |
| 2337 | read_only | pL = tp.get(f"{acct}_{symbol}_LONG") or {} |
| 2338 | read_only | has_long = abs(float(pL.get("size", 0) or 0.0)) > 0.0 |
| 2342 | read_only | pS = tp.get(f"{acct}_{symbol}_SHORT") or {} |
| 2343 | read_only | has_short = abs(float(pS.get("size", 0) or 0.0)) > 0.0 |
| 2361 | read_only | if not (isinstance(pos, dict) and pos.get('has_position')): |
| 2363 | read_only | current_side = str(pos.get('side', '') or '').upper() |
| 2408 | write_signal | Returns list of hedge signals to publish. |
| 2418 | read_only | # Get all open positions from Redis |
| 2419 | read_only | redis = getattr(self, 'redis', None) or getattr(self, '_signal_redis', None) |
| 2420 | read_only | if not redis: |
| 2425 | read_only | edge_gate = get_adaptive_edge_gate(redis_client=redis) |
| 2427 | read_only | # Get positions from portfolio tracker (correct Redis keys) |
| 2434 | read_only | pos_data = redis.hgetall(pos_key) |
| 2445 | read_only | size = abs(float(pos.get('size', 0))) |
| 2446 | read_only | if size > 0 and pos.get('has_position', False): |
| 2462 | read_only | symbol = pos.get('symbol') |
| 2463 | read_only | side = pos.get('side', '').upper() |
| 2464 | read_only | entry_price = float(pos.get('entry_price', 0) or pos.get('avg_entry', 0) or 0) |
| 2465 | read_only | current_price = float(pos.get('current_price', 0) or pos.get('mark_price', 0) or 0) |
| 2466 | read_only | size_qty = abs(float(pos.get('size', 0))) |
| 2468 | read_only | size_usd = size_qty * current_price if current_price > 0 else abs(float(pos.get('notional', 0) or pos.get('size_usd', 0) or 0)) |
| 2469 | read_only | leverage = float(pos.get('leverage', 1) or 1) |
| 2512 | read_only | leverage = float(pos.get('leverage', 1) or 1) |
| 2523 | read_only | edge_gate2 = get_adaptive_edge_gate(redis_client=redis) |
| 2577 | read_only | _mom_flag = redis.get(f"wma:momentum_regime:{symbol}") |
| 2597 | read_only | redis.setex(ride_key, _ride_ttl, json.dumps(ride_data)) |
| 2607 | write_metric | redis.delete(ride_key) |
| 2624 | read_only | _ep = float(pos.get('entry_price', 0) or pos.get('entryPrice', 0) or 0) |
| 2625 | read_only | _mp = float(pos.get('mark_price', 0) or pos.get('current_price', 0) or 0) |
| 2626 | read_only | _lv = float(pos.get('leverage', 1) or 1) |
| 2755 | write_metric | def _maybe_publish_recovery_reduction( |
| 2807 | read_only | used = int(counts.get(aid, 0) or 0) |
| 2821 | read_only | # but can also be keyed as "SYMBOL:LONG/SHORT" in some Redis fallbacks. |
| 2834 | read_only | if "side" not in p or not str(p.get("side") or "").strip(): |
| 2835 | read_only | ps = str(p.get("positionSide") or "").upper().strip() |
| 2839 | read_only | amt = float(p.get("positionAmt", 0) or 0.0) |
| 2849 | read_only | if p.get("margin_used") is None and p.get("initialMargin") is not None: |
| 2850 | read_only | p["margin_used"] = float(p.get("initialMargin") or 0.0) |
| 2854 | read_only | if p.get("entry_price") is None and p.get("entryPrice") is not None: |
| 2855 | read_only | p["entry_price"] = float(p.get("entryPrice") or 0.0) |
| 2859 | read_only | if p.get("mark_price") is None and p.get("markPrice") is not None: |
| 2860 | read_only | p["mark_price"] = float(p.get("markPrice") or 0.0) |
| 2867 | read_only | if p.get("unRealizedProfit") is None and p.get("unrealized_pnl_usd") is None and p.get("unrealized_pnl") is None: |
| 2868 | read_only | entry_px = float(p.get("entry_price", 0.0) or 0.0) |
| 2869 | read_only | mark_px = float(p.get("mark_price", 0.0) or 0.0) |
| 2870 | read_only | amt_raw = float(p.get("positionAmt", 0.0) or 0.0) |
| 2872 | read_only | side_eff = str(p.get("side") or "").upper() |
| 2882 | read_only | redis_client = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 2883 | read_only | if redis_client: |
| 2884 | read_only | raw = redis_client.hgetall(f"portfolio:positions:{aid}") or {} |
| 2913 | write_metric | pref_set = set(s.upper() for s in (preferred_symbols or []) if isinstance(s, str)) |
| 2936 | read_only | v = _safe_float(p.get(k), 0.0) |
| 2938 | read_only | if k == "pnl" and abs(v) <= 5.0 and (p.get("pnl_pct") is not None or p.get("roe_pct") is not None): |
| 2947 | read_only | if p.get(k) is not None: |
| 2949 | read_only | entry_px = _safe_float(p.get("entry_price", p.get("entryPrice", 0.0)), 0.0) |
| 2950 | read_only | mark_px = _safe_float(p.get("mark_price", p.get("markPrice", 0.0)), 0.0) |
| 2951 | read_only | amt = _safe_float(p.get("size", p.get("positionAmt", 0.0)), 0.0) |
| 2952 | read_only | side_eff = str(p.get("side") or p.get("positionSide") or "").upper() |
| 2959 | read_only | if k in p and p.get(k) is not None: |
| 2960 | read_only | v = _safe_float(p.get(k), 0.0) |
| 2983 | read_only | sym = str(p.get("symbol") or "").upper().strip() |
| 2988 | read_only | side = str(p.get("side") or p.get("positionSide") or "").upper().strip() |
| 2994 | read_only | size = float(p.get("size", p.get("positionAmt", 0)) or 0.0) |
| 2997 | read_only | if abs(size) <= 0.0 and not bool(p.get("has_position")): |
| 3000 | read_only | margin = float(p.get("margin_used", p.get("initialMargin", p.get("margin", 0))) or 0.0) |
| 3044 | write_metric | self._publish_skip_event( |
| 3063 | read_only | reduce_sym = str(best.get("symbol") or "").upper().strip() |
| 3064 | read_only | reduce_side = str(best.get("side") or "").upper().strip() or ("LONG" if "LONG" in reduce_sym else "") |
| 3067 | read_only | reduce_side = "LONG" if str(best.get("positionSide") or "").upper() == "LONG" else ("SHORT" if str(best.get("positionSide") or "").upper() == "SHORT" else "") |
| 3115 | read_only | counts[aid] = int(counts.get(aid, 0) or 0) + 1 |
| 3140 | write_signal | Canonical trade signal builder. ALL signals:trading publishes MUST use this. |
| 3147 | write_checkpoint_metadata | Complete payload ready for XADD, or None if blocked |
| 3158 | read_only | payload.get("bypass_gating") |
| 3159 | read_only | or payload.get("force_execute") |
| 3160 | read_only | or payload.get("gating_override") |
| 3170 | read_only | if 'model_action_id' not in payload and isinstance(base_fields.get('action'), int): |
| 3171 | read_only | payload['model_action_id'] = base_fields.get('action') |
| 3172 | read_only | payload['model_action_space'] = base_fields.get('model_action_space', 'hedge_rl') |
| 3182 | read_only | payload.get("final_action") |
| 3183 | read_only | or payload.get("action_name") |
| 3184 | read_only | or payload.get("action") |
| 3185 | read_only | or payload.get("predicted_action") |
| 3194 | read_only | if not payload.get("structural_regime"): |
| 3195 | read_only | structural = self._get_structural_regime_context(str(payload.get("symbol") or "")) |
| 3196 | read_only | payload["structural_regime"] = structural.get("effective_regime") |
| 3197 | read_only | payload["macro_regime"] = structural.get("macro_regime") |
| 3198 | read_only | payload["structural_time_in_state_days"] = structural.get("time_in_state_days") |
| 3199 | read_only | payload["structural_metrics"] = structural.get("metrics") |
| 3200 | read_only | payload["risk_mode"] = structural.get("risk_mode") |
| 3208 | read_only | cp = payload.get("current_position") or {} |
| 3210 | read_only | (cp.get("side") if isinstance(cp, dict) else None) |
| 3211 | read_only | or payload.get("current_position_side") |
| 3212 | read_only | or payload.get("side") |
| 3234 | read_only | payload["final_action"] = payload.get("action_name") |
| 3286 | read_only | symbol = str(payload.get("symbol") or "") |
| 3287 | read_only | timeframe = str(payload.get("timeframe") or payload.get("tf") or "") |
| 3288 | read_only | conf_for_target = _f(payload.get("confidence") or payload.get("model_confidence") or 0.0) |
| 3292 | read_only | payload.get("trigger_price") |
| 3293 | read_only | or payload.get("entry_price") |
| 3294 | read_only | or payload.get("price") |
| 3295 | read_only | or payload.get("mark_price") |
| 3296 | read_only | or payload.get("current_price") |
| 3299 | read_only | action_u = str(payload.get("action_name") or "").upper() |
| 3301 | read_only | # If no explicit price context is present in the signal, fall back to the live Redis mark price. |
| 3304 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 3306 | read_only | px = rc.get(f"price:{symbol}") |
| 3342 | read_only | atr_pct = float(payload.get("atr_pct") or 0.0) |
| 3345 | read_only | _rc = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 3350 | read_only | atr_pct = max(0.0, _f(payload.get("market_volatility") or payload.get("volatility") or 0.0)) |
| 3354 | read_only | _pt = _compute_price_target( |
| 3372 | read_only | _ec_decided_flip = bool(payload.get("exposure_controller")) |
| 3376 | read_only | aid = str(payload.get("account_id") or payload.get("account") or "primary").strip().lower() |
| 3380 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 3381 | read_only | raw_leg = rc.hget(f"portfolio:positions:{aid}", f"{payload.get('symbol')}:{hedge_side}") if rc else None |
| 3385 | read_only | exists = abs(float((leg or {}).get("size", 0) or 0.0)) > 1e-12 |
| 3406 | read_only | action_name_eff = payload.get("action_name") or action_name |
| 3407 | read_only | cat_eff = str(payload.get("action_category") or get_action_category(str(action_name_eff))).upper() |
| 3415 | read_only | payload['sizing_source'] = payload.get('sizing_source', 'reduce_only') |
| 3422 | read_only | symbol = payload.get('symbol', 'UNKNOWN') |
| 3423 | read_only | leverage = float(payload.get('leverage') or payload.get('recommended_leverage') or 0) |
| 3424 | read_only | margin_usd = float(payload.get('margin_usd') or 0) |
| 3425 | read_only | notional_usd = float(payload.get('notional_usd') or 0) |
| 3426 | read_only | position_size_pct = float(payload.get('position_size_pct') or payload.get('recommended_position_pct') or 0) |
| 3427 | read_only | confidence = float(payload.get('confidence') or payload.get('model_confidence') or 0.5) |
| 3432 | read_only | equity_usd = float(sizing_ctx.get('equity_usd', 0) or sizing_ctx.get('equity', 0) or 0) |
| 3458 | read_only | if hasattr(self, 'redis') and self.redis: |
| 3459 | read_only | _ks_all = self.redis.get("killswitch:all_april_plan") |
| 3463 | read_only | # Fetch tactical data from Redis |
| 3466 | read_only | if hasattr(self, 'redis') and self.redis: |
| 3469 | read_only | _uf = self.redis.hgetall(f"unified_features:{symbol}:{_tf}") |
| 3479 | read_only | _ms = self.redis.hgetall(f"msnap:coinapi_wsds:{symbol}") |
| 3500 | read_only | _liq_dist = float(_tac_features.get("liquidation_short_distance_pct", 100)) |
| 3501 | read_only | _liq_str = float(_tac_features.get("liquidation_short_strength", 0)) |
| 3503 | read_only | _liq_dist = float(_tac_features.get("liquidation_long_distance_pct", 100)) |
| 3504 | read_only | _liq_str = float(_tac_features.get("liquidation_long_strength", 0)) |
| 3506 | read_only | _spoof = float(_tac_micro.get("depth_spoof_score_v2", _tac_micro.get("depth_spoof_score_v1", 0))) |
| 3507 | read_only | _flow_5s = float(_tac_micro.get("depth_trade_imbalance_5s", 0)) |
| 3508 | read_only | _fast_move = float(_tac_micro.get("depth_fast_move_score_1m", 0)) |
| 3518 | read_only | _funding = float(_tac_features.get("funding_rate", 0)) |
| 3523 | read_only | _whale_imb = float(_tac_features.get("coinank_bigorder_imbalance", _tac_features.get("bigorder_imbalance", 0))) |
| 3529 | read_only | _adx = float(_tac_features.get("ind_ta_adx_14", 0)) |
| 3530 | read_only | _rsi = float(_tac_features.get("ind_ta_rsi_14", 50)) |
| 3531 | read_only | _macd = float(_tac_features.get("ind_ta_macd_line", 0)) |
| 3555 | read_only | base_pct = _tier_sizes.get(tactical_tier, TACTICAL_TIER4_SIZE_PCT) |
| 3583 | read_only | lev_cfg = SYMBOL_LEVERAGE_CONFIG.get(symbol, SYMBOL_LEVERAGE_CONFIG.get('default', {})) |
| 3584 | read_only | min_lev = float(lev_cfg.get('min_leverage', 10)) |
| 3585 | read_only | max_lev = float(lev_cfg.get('max_leverage', 25)) |
| 3596 | read_only | # Uses live NATR from Redis — no static thresholds. |
| 3599 | read_only | if hasattr(self, 'redis') and self.redis: |
| 3602 | read_only | _vol_raw = self.redis.hget(f"unified_features:{symbol}:{_vol_tf}", "natr") |
| 3637 | read_only | payload['sizing_source'] = payload.get('sizing_source', 'upstream') |
| 3640 | read_only | constraints = list(payload.get("constraints_applied", []) or []) |
| 3648 | read_only | liq = (self._last_liquidity_gate_result or {}).get(symbol, {}) or {} |
| 3650 | read_only | liq_min = float(liq.get("min_depth_usd") or 0.0) |
| 3654 | read_only | liq_warn = float(liq.get("warn_depth_usd") or 0.0) |
| 3658 | read_only | liq_depth = float(liq.get("depth_usd") or 0.0) |
| 3750 | read_only | action_category = payload.get("action_category") or payload.get("category") or "" |
| 3753 | read_only | is_hedge_action = (str(action_category).upper() == "HEDGE") or ("HEDGE" in action_upper) or bool(payload.get("hedge_intent")) |
| 3772 | read_only | acct_raw = payload.get("account_id") |
| 3783 | write_metric | f"caps enforced per-account during publish" |
| 3804 | read_only | fastlane_hint = bool(payload.get("fastlane")) or bool(payload.get("is_flash_move")) or float(payload.get("flash_move_pct", 0.0) or 0.0) != 0.0 |
| 3853 | read_only | if payload.get("notional_usd"): |
| 3854 | read_only | payload["notional_usd"] = float(payload.get("notional_usd")) * float(scale) |
| 3856 | read_only | lev = float(payload.get("leverage") or payload.get("recommended_leverage") or 0.0) or 0.0 |
| 3876 | write_checkpoint_metadata | self._publish_skip_event(payload, "HEADROOM_RESERVE_BLOCK", msg) |
| 3882 | read_only | getattr(self, "_signal_redis", None) or getattr(self, "redis", None), |
| 3906 | read_only | ecf_account = str(payload.get("account_id") or acct or "").strip().lower() |
| 3919 | read_only | getattr(self, "_signal_redis", None) or getattr(self, "redis", None), |
| 3937 | write_signal | self._publish_signal_payload(s, contract_required=False) |
| 3943 | read_only | if not payload.get("_headroom_reserve_resized"): |
| 3953 | write_checkpoint_metadata | self._publish_skip_event(payload, "PORTFOLIO_CAP_BLOCK", msg) |
| 3958 | write_metric | self._maybe_publish_recovery_reduction( |
| 3959 | read_only | account_id=str(acct) if acct is not None else str(payload.get("account_id") or ""), |
| 3997 | read_only | sym_min = float((BINANCE_FUTURES_MIN_NOTIONAL_USD_BY_SYMBOL or {}).get(symbol, MIN_NOTIONAL_USD) or MIN_NOTIONAL_USD) |
| 4035 | read_only | payload['signal_id'] = payload.get('signal_id') or str(uuid.uuid4()) |
| 4036 | read_only | payload['ts_ms'] = payload.get('ts_ms') or int(time.time() * 1000) |
| 4038 | read_only | _acct = str(payload.get('account_id') or payload.get('account') or 'primary').strip().lower() or 'primary' |
| 4039 | read_only | _sym = str(payload.get('symbol') or '').upper() |
| 4040 | read_only | _tf = str(payload.get('timeframe') or payload.get('tf') or '').lower() |
| 4041 | read_only | payload['decision_id'] = payload.get('decision_id') or f"{int(payload['ts_ms'])}-{_sym}-{_tf}-{_acct}" |
| 4057 | read_only | acct_raw = payload.get("account_id") |
| 4068 | read_only | risk_blob = self._signal_redis.get(risk_key) |
| 4077 | read_only | block_categories = risk_state.get("block_categories") or ["OPEN_RISK"] |
| 4079 | read_only | action_category = str(payload.get('action_category') or '').upper() |
| 4081 | write_signal | if action_category and action_category in set(block_categories): |
| 4082 | read_only | reason = str(risk_state.get("reason") or risk_state.get("event_type") or "risk_off") |
| 4086 | write_checkpoint_metadata | self._publish_skip_event(payload, "RISK_OFF_BLOCK", reason) |
| 4102 | read_only | conf_raw = float(payload.get('confidence') or payload.get('model_confidence') or 0) |
| 4144 | read_only | account_id = str(sig.get("account_id") or "").strip().lower() |
| 4145 | read_only | target_symbol = str(sig.get("symbol") or "").upper().strip() |
| 4146 | read_only | needed_margin = float(sig.get("target_margin_usd") or 0.0) |
| 4157 | read_only | r = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 4158 | read_only | target_check = r.hget(f"portfolio:positions:{account_id}", f"{target_symbol}:LONG") or \ |
| 4159 | read_only | r.hget(f"portfolio:positions:{account_id}", f"{target_symbol}:SHORT") |
| 4173 | read_only | r = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 4174 | read_only | raw = r.hgetall(f"portfolio:positions:{account_id}") or {} |
| 4203 | read_only | sym = str(p.get("symbol") or "").upper().strip() |
| 4204 | read_only | side = str(p.get("side") or p.get("positionSide") or "").upper().strip() |
| 4210 | read_only | margin_used = float(p.get("margin_used") or p.get("initialMargin") or 0.0) |
| 4215 | read_only | pnl_usd = float(p.get("unrealized_pnl") or p.get("unRealizedProfit") or p.get("unrealized_pnl_usd") or 0.0) |
| 4227 | write_metric | self._publish_skip_event( |
| 4284 | read_only | r = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 4297 | read_only | "donors": [s.get("symbol") for s in signals], |
| 4298 | read_only | "actions": [s.get("action_name") for s in signals], |
| 4318 | read_only | r = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 4325 | read_only | hm = HedgeManagerV3(redis_client=r) |
| 4328 | read_only | raw = r.hgetall(f"portfolio:positions:{account_id}") or {} |
| 4362 | read_only | main = legs.get("LONG") or legs.get("SHORT") or {} |
| 4365 | read_only | micro = r.hgetall(f"msnap:coinapi_wsds:{sym}") or {} |
| 4397 | read_only | symbol_min = float(symbol_cfg.get("min_leverage", 1)) |
| 4398 | read_only | symbol_max = float(symbol_cfg.get("max_leverage", 25)) |
| 4454 | read_only | symbol = str(payload.get("symbol") or "").strip().upper() |
| 4458 | read_only | action_name = str(payload.get("action_name") or payload.get("action") or "").upper() |
| 4459 | read_only | category = str(payload.get("action_category") or get_action_category(action_name)).upper() |
| 4460 | read_only | is_hedge = bool(payload.get("hedge_intent")) or category == "HEDGE" or action_name.startswith(("OPEN_HEDGE_", "ADD_HEDGE_")) |
| 4464 | read_only | conf = float(payload.get("confidence", payload.get("model_confidence", 0.0)) or 0.0) |
| 4472 | read_only | sym_cfg = SYMBOL_LEVERAGE_CONFIG.get(symbol) or SYMBOL_LEVERAGE_CONFIG.get("default") or {} |
| 4474 | read_only | min_lev = float(sym_cfg.get("min_leverage", 1.0) or 1.0) |
| 4475 | read_only | max_lev = float(sym_cfg.get("max_leverage", 25.0) or 25.0) |
| 4484 | read_only | aid = str(payload.get("account_id") or payload.get("account") or "primary").strip().lower() |
| 4487 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 4488 | read_only | raw = rc.hget(f"portfolio:positions:{aid}", f"{symbol}:{side}") if rc else None |
| 4492 | read_only | existing_lev = float((leg or {}).get("leverage", 0.0) or 0.0) |
| 4498 | read_only | # Risk inputs: try payload first; optionally fetch from Redis. |
| 4510 | read_only | atr_pct = _f(payload.get(k)) |
| 4513 | read_only | spread_pct = _f(payload.get(k)) |
| 4516 | read_only | tox = _f(payload.get(k)) |
| 4520 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 4522 | read_only | feat = rc.hgetall(f"features:unified:{symbol}:{tf}") if rc else {} |
| 4525 | read_only | v = feat.get(name) |
| 4569 | read_only | aid = str(payload.get("account_id") or payload.get("account") or "primary").strip().lower() |
| 4570 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 4571 | read_only | raw = rc.get(f"portfolio:equity:{aid}") if rc else None |
| 4575 | read_only | eq = float(j.get("equity_usd", j.get("total_balance", 0.0)) or 0.0) |
| 4576 | read_only | avail = j.get("available_margin_usd") or j.get("available_usd") or j.get("available_balance") or j.get("available") or 0.0 |
| 4646 | read_only | ts_ms = int(p.get("ts_ms") or p.get("timestamp_ms") or p.get("timestamp", time.time()) * 1000) |
| 4648 | read_only | p["timestamp"] = p.get("timestamp") or (ts_ms / 1000.0) |
| 4655 | read_only | p["signal_id"] = p.get("signal_id") or str(uuid.uuid4()) |
| 4658 | read_only | _acct = str(p.get("account_id") or p.get("account") or "primary").strip().lower() or "primary" |
| 4659 | read_only | _sym = str(p.get("symbol") or "").upper() |
| 4660 | read_only | _tf = str(p.get("timeframe") or p.get("tf") or "").lower() |
| 4661 | read_only | p["decision_id"] = p.get("decision_id") or f"{int(ts_ms)}-{_sym}-{_tf}-{_acct}" |
| 4665 | read_only | symbol = p.get("symbol") |
| 4666 | read_only | timeframe = p.get("timeframe") or p.get("tf") |
| 4667 | read_only | action = str(p.get("action") or p.get("action_name") or "UNKNOWN").upper() |
| 4676 | write_metric | p["source"] = p.get("source") or getattr(self.main_config, "PUBLISH_SOURCE_TAG", "trainer") |
| 4677 | read_only | p["model"] = p.get("model") or "ppo_masa_lstm" |
| 4680 | read_only | conf = float(p.get("confidence", p.get("model_confidence", 0.0)) or 0.0) |
| 4723 | read_only | leverage = p.get("recommended_leverage", p.get("leverage", 1.0)) |
| 4726 | read_only | p["leverage_source"] = p.get("leverage_source") or "adaptive_engine" |
| 4741 | read_only | pos_pct = p.get("recommended_position_pct", p.get("position_size_pct")) |
| 4745 | read_only | margin_usd = p.get("margin_usd") |
| 4746 | read_only | notional_usd = p.get("notional_usd") |
| 4752 | read_only | p["notional_usd"] = float(notional_usd) if notional_usd is not None else p.get("notional_usd", 0.0) |
| 4767 | read_only | if not p.get(field): |
| 4773 | read_only | if p.get("margin_usd", 0.0) <= 0: |
| 4775 | read_only | if p.get("leverage", 0.0) <= 0: |
| 4777 | read_only | pos_pct_present = p.get("recommended_position_pct") is not None or p.get("position_size_pct") is not None |
| 4780 | read_only | if p.get("notional_usd", 0.0) <= 0: |
| 4787 | read_only | if action_type in {"open", "flip", "increase"} and p.get("margin_usd", 0.0) > 0: |
| 4788 | read_only | p["sizing_source"] = p.get("sizing_source") or "portfolio_pct" |
| 4794 | write_signal | def _publish_signal_payload(self, payload: dict, *, stream: str = None, contract_required: bool = True): |
| 4796 | write_signal | Publish via canonical builder with comprehensive signal state management. |
| 4819 | read_only | forced_regime = get_flag_env(self.redis, "FORCE_REGIME", None) if callable(get_flag_env) else None |
| 4822 | read_only | regime_label = str(forced_regime or payload.get("regime") or payload.get("market_regime") or "").upper().strip() |
| 4825 | read_only | f"REGIME_CLASS / account={payload.get('account_id') or payload.get('account') or 'unknown'} / " |
| 4826 | read_only | f"symbol={payload.get('symbol')} / action={payload.get('action') or payload.get('action_name')} / " |
| 4833 | write_risk_state | # FORBIDDEN_DIRECT_PUBLISH GUARD (Jan 2026) |
| 4834 | write_metric | # When ORCHESTRATOR_WORKER_MODE=publish, only the orchestrator worker |
| 4835 | write_signal | # should publish to signals:live:*. All modules must use _emit_proposal(). |
| 4836 | write_metric | # Direct publishes are logged and DROPPED. |
| 4842 | write_metric | ORCHESTRATOR_FORBIDDEN_PUBLISH_STREAM, |
| 4845 | write_metric | if ORCHESTRATOR_WORKER_ENABLED and str(ORCHESTRATOR_WORKER_MODE).lower() == "publish": |
| 4846 | write_signal | # Emergency-only bypass: STRICTLY requires all 4 conditions set by _publish_signal_unified: |
| 4855 | read_only | action_u = str(payload.get("action") or payload.get("action_name") or "").upper() |
| 4858 | read_only | _urgency_v = str(payload.get("urgency") or "").upper() |
| 4864 | read_only | int(payload.get("emergency_bypass") or 0) == 1 |
| 4874 | write_risk_state | "⚡ [FORBIDDEN_GUARD_BYPASS] emergency risk-reducing direct publish / " |
| 4876 | read_only | payload.get("action"), payload.get("account_id"), payload.get("symbol"), |
| 4879 | write_metric | # In publish mode, direct publish is FORBIDDEN |
| 4880 | read_only | source = payload.get("source") or payload.get("source_module") or "unknown" |
| 4881 | read_only | symbol = payload.get("symbol") or "UNKNOWN" |
| 4882 | read_only | action = payload.get("action") or payload.get("action_name") or "UNKNOWN" |
| 4883 | read_only | account_id = payload.get("account_id") or "unknown" |
| 4887 | write_signal | f"🚫 [FORBIDDEN_DIRECT_PUBLISH] {account_id}:{symbol} {action} from {source} " |
| 4888 | write_metric | f"- direct publish blocked in ORCHESTRATOR_WORKER_MODE=publish. " |
| 4894 | read_only | redis_client = ( |
| 4895 | read_only | getattr(self, "_signal_redis", None) |
| 4896 | read_only | or getattr(self, "redis", None) |
| 4897 | read_only | or getattr(getattr(self, "ppo_model", None), "_signal_redis", None) |
| 4899 | read_only | if redis_client: |
| 4901 | write_metric | "event": "FORBIDDEN_DIRECT_PUBLISH", |
| 4910 | write_metric | redis_client.xadd( |
| 4911 | write_metric | ORCHESTRATOR_FORBIDDEN_PUBLISH_STREAM or "wma:forbidden_publishes", |
| 4917 | write_signal | # DROP the signal - do not publish |
| 4921 | write_metric | # Config not available, allow publish (shadow mode default) |
| 4924 | write_risk_state | logger.debug(f"[FORBIDDEN_GUARD] Check failed (allowing publish): {guard_err}") |
| 4927 | read_only | action_type = self._classify_action_type(payload.get("action") or payload.get("action_name")) |
| 4946 | read_only | symbol = payload.get('symbol') |
| 4950 | read_only | action_raw = payload.get('action_name') or payload.get('action') or '' |
| 4959 | write_metric | # This is enforced at publish time to prevent any module from bypassing no-loss safety |
| 4961 | read_only | if payload.get("profit_intent") is True: |
| 4965 | write_checkpoint_metadata | # Option D (No-Loss Flip Conversion): never publish flip-style CLOSE_*_AND_OPEN_* |
| 4974 | read_only | act_u = str(payload.get("action_name") or "").upper() |
| 4982 | read_only | payload.get("account_id") |
| 4983 | read_only | or payload.get("account") |
| 4984 | read_only | or payload.get("target_account_id") |
| 4998 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 4999 | read_only | sym = str(payload.get("symbol") or "").upper() |
| 5000 | read_only | raw_leg = rc.hget(f"portfolio:positions:{aid}", f"{sym}:{hedge_side}") if rc else None |
| 5003 | read_only | exists = abs(float((leg or {}).get("size", 0) or 0.0)) > 1e-12 |
| 5019 | write_metric | # Change 1: Hedge sizing “headroom-aware” at publish time |
| 5020 | write_metric | # - If a hedge add would be blocked downstream due to no free margin, publish a downsized hedge. |
| 5021 | write_metric | # This prevents publish→drop loops and reduces cap-hit spam. |
| 5025 | write_metric | HEDGE_PUBLISH_HEADROOM_AWARE, |
| 5026 | write_metric | HEDGE_PUBLISH_HEADROOM_BUFFER_PCT, |
| 5031 | write_metric | HEDGE_PUBLISH_HEADROOM_AWARE = False |
| 5032 | write_metric | HEDGE_PUBLISH_HEADROOM_BUFFER_PCT = 95.0 |
| 5037 | read_only | cat_u = str(payload.get("action_category") or _get_action_category(action_name)).upper() |
| 5041 | read_only | is_hedge_sig = bool(payload.get("hedge_intent")) or (cat_u == "HEDGE") or str(action_name or "").upper().startswith(("OPEN_HEDGE_", "ADD_HEDGE_")) |
| 5042 | write_metric | if bool(HEDGE_PUBLISH_HEADROOM_AWARE) and is_hedge_sig: |
| 5046 | read_only | payload.get("account_id") |
| 5047 | read_only | or payload.get("account") |
| 5048 | read_only | or payload.get("target_account_id") |
| 5057 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 5058 | read_only | eq_raw = rc.get(f"portfolio:equity:{aid}") if rc else None |
| 5062 | read_only | eq_usd = float(eqj.get("equity_usd", eqj.get("total_balance", 0.0)) or 0.0) if isinstance(eqj, dict) else 0.0 |
| 5064 | read_only | eqj.get("available_margin_usd") |
| 5065 | read_only | or eqj.get("available_usd") |
| 5066 | read_only | or eqj.get("available_balance") |
| 5067 | read_only | or eqj.get("available") |
| 5071 | read_only | eqj.get("used_margin_usd") |
| 5072 | read_only | or eqj.get("total_margin_used") |
| 5073 | read_only | or eqj.get("used_margin") |
| 5087 | read_only | mreq = float(payload.get("margin_usd", 0.0) or 0.0) |
| 5092 | read_only | notional = float(payload.get("notional_usd", 0.0) or 0.0) |
| 5096 | read_only | lev = float(payload.get("leverage", payload.get("recommended_leverage", 10)) or 10.0) |
| 5103 | write_metric | buffer = max(50.0, min(99.0, float(HEDGE_PUBLISH_HEADROOM_BUFFER_PCT or 95.0))) |
| 5114 | read_only | payload["margin_usd"] = float(payload.get("margin_usd", mreq) or mreq) * scale |
| 5118 | read_only | payload["notional_usd"] = float(payload.get("notional_usd", 0.0) or 0.0) * scale |
| 5122 | read_only | payload["position_size_pct"] = float(payload.get("position_size_pct", 0.0) or 0.0) * scale |
| 5137 | read_only | payload.get("account_id") |
| 5138 | read_only | or payload.get("account") |
| 5139 | read_only | or payload.get("target_account_id") |
| 5150 | read_only | raw_pos = self._signal_redis.hgetall(pos_key) if getattr(self, '_signal_redis', None) else {} |
| 5161 | read_only | has_long = str(raw_pos.get('has_long', 'False')).lower() == 'true' |
| 5162 | read_only | has_short = str(raw_pos.get('has_short', 'False')).lower() == 'true' |
| 5190 | read_only | _cat_u = str(payload.get("action_category") or "").upper() |
| 5194 | read_only | _is_hedge_increase = bool(payload.get("hedge_intent")) or (_cat_u == "HEDGE") or ("HEDGE" in _act_u) |
| 5198 | read_only | logger.info(f"🛡️ [HEDGE_BYPASS] INCREASE_VALIDATION bypassed / {payload.get('symbol')} {action_name}") |
| 5200 | read_only | symbol_for_val = payload.get('symbol') |
| 5201 | read_only | account_id_for_val = payload.get('account_id', 'unknown') |
| 5202 | read_only | confidence_for_val = payload.get('confidence', 0) or 0 |
| 5204 | write_metric | # Build a per-leg snapshot directly from Redis-published trader positions. |
| 5210 | read_only | raw = self.redis.hgetall(pos_key) if getattr(self, 'redis', None) else {} |
| 5225 | read_only | has_long = str(raw.get('has_long', 'False')) == 'True' |
| 5226 | read_only | has_short = str(raw.get('has_short', 'False')) == 'True' |
| 5232 | read_only | if has_long and raw.get('long'): |
| 5233 | read_only | long_leg = json.loads(raw.get('long') or '{}') |
| 5237 | read_only | if has_short and raw.get('short'): |
| 5238 | read_only | short_leg = json.loads(raw.get('short') or '{}') |
| 5248 | read_only | liq_distance_pct = float(chosen.get('buffer_percent', 0) or 0) |
| 5253 | read_only | 'has_position': bool(chosen.get('has_position', False)) and float(chosen.get('size', 0) or 0) > 0, |
| 5255 | read_only | 'pnl_pct': float(chosen.get('pnl_pct', 0) or 0), |
| 5256 | read_only | 'leverage': float(chosen.get('leverage', 0) or 0), |
| 5259 | read_only | 'long_pnl_pct': float(long_leg.get('pnl_pct', 0) or 0), |
| 5260 | read_only | 'short_pnl_pct': float(short_leg.get('pnl_pct', 0) or 0), |
| 5280 | write_risk_state | # This keeps OPEN_RISK alive and avoids publish→drop starvation loops. |
| 5292 | write_metric | # Publish skip event for observability |
| 5294 | write_checkpoint_metadata | self._publish_skip_event(payload, f"INCREASE_VALIDATION_FAILED", reason) |
| 5304 | read_only | pos_lev = float((current_position or {}).get('leverage', 0) or 0) |
| 5317 | read_only | _cat_u = str(payload.get("action_category") or "").upper() |
| 5320 | read_only | if bool(payload.get("hedge_intent")) or (_cat_u == "HEDGE") or ("HEDGE" in str(action_name or "").upper()): |
| 5323 | read_only | logger.warning(f"🛡️ [HEDGE_BYPASS] INCREASE_VALIDATION_ERROR bypassed / {payload.get('symbol')} {action_name}: {val_err}") |
| 5328 | read_only | a = payload.get("action") |
| 5347 | read_only | if ENABLE_PRICE_TARGET_PREDICTION and payload.get("price_target") is None: |
| 5349 | read_only | symbol_for_target = str(payload.get("symbol") or "") |
| 5350 | read_only | tf_for_target = str(payload.get("timeframe") or payload.get("tf") or "") |
| 5351 | read_only | action_u = str(action_name or payload.get("action") or "").upper() |
| 5386 | read_only | conf_for_target = _f(payload.get("confidence") or payload.get("model_confidence") or 0.0) |
| 5388 | read_only | payload.get("trigger_price") |
| 5389 | read_only | or payload.get("entry_price") |
| 5390 | read_only | or payload.get("price") |
| 5391 | read_only | or payload.get("mark_price") |
| 5392 | read_only | or payload.get("current_price") |
| 5393 | read_only | or payload.get("close") |
| 5394 | read_only | or payload.get("last_price") |
| 5398 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 5400 | read_only | current_px = _parse_live_price(rc.get(f"price:{symbol_for_target}")) |
| 5407 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 5413 | read_only | h = rc.hgetall(f"unified_features:{symbol_for_target}:{tf_k}") or {} |
| 5439 | read_only | if k in h and h.get(k) is not None: |
| 5440 | read_only | current_px = _parse_live_price(h.get(k)) |
| 5449 | read_only | ob_raw = rc.get(f"orderbook:top:{symbol_for_target}") |
| 5461 | read_only | if not payload.get("current_price"): |
| 5463 | read_only | if not payload.get("price"): |
| 5498 | read_only | atr_pct = float(payload.get("atr_pct") or 0.0) |
| 5501 | read_only | _rc = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 5506 | read_only | _pt = _compute_price_target( |
| 5515 | read_only | action_category = payload.get('action_category') or get_action_category(action_name) |
| 5530 | write_metric | # and publish per-account (combined view is telemetry only). |
| 5538 | read_only | _requested_account_id = payload.get("account_id") or payload.get("account") or payload.get("target_account_id") |
| 5539 | read_only | _source_tag = str(payload.get("source") or "").strip().lower() |
| 5545 | read_only | # Redis client (prefer trainer's configured client) |
| 5546 | read_only | redis_client = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 5547 | read_only | if redis_client is None: |
| 5549 | read_only | from utils.redis_client import get_redis |
| 5550 | read_only | redis_client = get_redis() |
| 5552 | read_only | redis_client = None |
| 5564 | read_only | if not redis_client: |
| 5567 | read_only | raw = redis_client.hget(f"portfolio:positions:{account_id}", f"{symbol}:{side}") |
| 5578 | read_only | def _pos_exists(pos) -> bool: |
| 5582 | read_only | if not bool(pos.get("has_position", True)): |
| 5587 | read_only | sz = abs(float(pos.get("size", 0) or 0)) |
| 5596 | write_metric | # Prefer explicit notional published by traders if present |
| 5597 | read_only | n = float(pos.get("notional", 0) or pos.get("size_usd", 0) or 0) |
| 5603 | read_only | sz = abs(float(pos.get("size", 0) or 0)) |
| 5604 | read_only | px = float(pos.get("mark_price") or pos.get("current_price") or pos.get("entry_price") or 0) |
| 5646 | read_only | and (not payload.get("_broadcast_open_multi_account")) |
| 5655 | read_only | f"source={payload.get('source','')} requested={_requested_account_id}" |
| 5666 | write_signal | res = self._publish_signal_payload(p2, stream=stream, contract_required=contract_required) |
| 5685 | write_signal | # - For actions requiring an existing leg (close/increase/hedge/flip): publish ONLY to accounts |
| 5697 | read_only | if _pos_exists(_load_leg_pos(aid, required_existing_side)): |
| 5701 | write_metric | self._publish_skip_event( |
| 5711 | write_metric | # If multiple accounts are eligible, publish per-account independently. |
| 5720 | write_metric | # Re-enter publish path per account (dedupe/caps/sizing are all account-scoped) |
| 5721 | write_signal | res = self._publish_signal_payload(p2, stream=stream, contract_required=contract_required) |
| 5746 | read_only | if req_acct in accounts and _pos_exists(_load_leg_pos(req_acct, required_existing_side)): |
| 5753 | read_only | if not _pos_exists(pos): |
| 5763 | write_metric | self._publish_skip_event( |
| 5783 | read_only | conf_for_policy = float(payload.get("confidence") or payload.get("model_confidence") or 0.0) |
| 5790 | read_only | payload.get("position_size_pct") |
| 5791 | read_only | or payload.get("recommended_position_pct") |
| 5792 | read_only | or payload.get("position_pct") |
| 5799 | read_only | lev_for_policy = float(payload.get("leverage") or payload.get("recommended_leverage") or 1.0) |
| 5806 | write_metric | # Prefer per-account equity snapshots published by traders (canonical, account-scoped). |
| 5810 | read_only | if redis_client: |
| 5811 | read_only | raw_eq = redis_client.get(f"portfolio:equity:{aid}") |
| 5815 | read_only | eq = float(pdata.get("equity_usd", 0.0) or 0.0) |
| 5816 | read_only | avail = float(pdata.get("available_margin_usd", 0.0) or 0.0) |
| 5817 | read_only | used = float(pdata.get("used_margin_usd", 0.0) or 0.0) |
| 5825 | read_only | eq = float(state.get("total_balance", 0) or 0.0) |
| 5826 | read_only | avail = float(state.get("available_balance", 0) or 0.0) |
| 5827 | read_only | util = float(state.get("margin_utilization_pct", 0.0) or 0.0) |
| 5839 | read_only | upstream_margin = float(payload.get("margin_usd") or 0.0) |
| 5854 | read_only | is_hedge=bool(payload.get("hedge_intent")), |
| 5879 | read_only | if redis_client: |
| 5880 | read_only | v = redis_client.get(rr_key) |
| 5886 | write_metric | eligible_ids = sorted(set(eligible_ids)) |
| 5895 | read_only | if redis_client: |
| 5896 | write_metric | redis_client.set(rr_key, str((rr + 1) % 1000000)) |
| 5912 | write_metric | # Prefer canonical per-account equity snapshot (published by traders) |
| 5916 | read_only | if redis_client: |
| 5917 | read_only | raw_eq = redis_client.get(f"portfolio:equity:{chosen_account}") |
| 5921 | read_only | eq = float(pdata.get("equity_usd", 0.0) or 0.0) |
| 5922 | read_only | avail = float(pdata.get("available_margin_usd", 0.0) or 0.0) |
| 5923 | read_only | used = float(pdata.get("used_margin_usd", 0.0) or 0.0) |
| 5931 | read_only | eq = float(st.get("total_balance", 0) or 0.0) |
| 5932 | read_only | avail = float(st.get("available_balance", 0) or 0.0) |
| 5933 | read_only | used = float(st.get("total_margin_used", 0) or 0.0) |
| 5934 | read_only | util = float(st.get("margin_utilization_pct", 0.0) or 0.0) |
| 5935 | read_only | tmb = float(st.get("total_margin_balance", eq) or eq) |
| 5944 | read_only | pct = float(payload.get("position_size_pct") or payload.get("recommended_position_pct") or 0.0) |
| 5948 | read_only | lev = float(payload.get("leverage") or payload.get("recommended_leverage") or 1.0) |
| 5981 | read_only | payload.get("bypass_gating") |
| 5982 | read_only | or payload.get("force_execute") |
| 5983 | read_only | or payload.get("gating_override") |
| 5986 | read_only | _action_u = str(payload.get("action_name") or payload.get("action") or "").upper() |
| 5991 | read_only | payload.get("source_module") |
| 5992 | read_only | or payload.get("source") |
| 5993 | read_only | or payload.get("decision_source") |
| 6053 | read_only | payload_conf = float(payload.get("confidence") or payload.get("model_confidence") or 0.0) |
| 6076 | write_metric | # do NOT publish FULL profit exits when ride-the-move is active for that symbol+side. |
| 6082 | read_only | if symbol and action_type == "close" and bool(payload.get("profit_intent")) and self._signal_redis: |
| 6091 | read_only | raw = self._signal_redis.get(ride_key) |
| 6095 | read_only | if isinstance(ride, dict) and bool(ride.get("suppress_tp")): |
| 6096 | read_only | ride_side = str(ride.get("side") or "").upper() |
| 6102 | read_only | if payload.get("close_fraction") is not None: |
| 6103 | read_only | close_fraction = float(payload.get("close_fraction") or 0.0) |
| 6104 | read_only | elif payload.get("close_pct") is not None: |
| 6105 | read_only | close_fraction = float(payload.get("close_pct") or 0.0) / 100.0 |
| 6119 | read_only | payload.get("reversal_confirmed") |
| 6120 | read_only | or payload.get("ride_move_allow_full_tp") |
| 6121 | read_only | or payload.get("force_execute") |
| 6122 | read_only | or payload.get("gating_override") |
| 6125 | read_only | why = str(ride.get("reason") or "ride_move") |
| 6127 | write_checkpoint_metadata | self._publish_skip_event(payload, "RIDE_MOVE_SUPPRESS_TP", f"{why} side={close_side} full_exit_blocked") |
| 6139 | read_only | current_price = float(payload.get('trigger_price') or payload.get('entry_price') or |
| 6140 | read_only | payload.get('price') or 0) |
| 6158 | read_only | confidence = float(payload.get('confidence') or payload.get('model_confidence') or 0) |
| 6159 | read_only | timeframe = payload.get('timeframe', 'multi') |
| 6168 | write_metric | # - First sighting: stage → do NOT publish to traders |
| 6169 | write_signal | # - Next cycle with same action: publish (unless microstructure suggests delay) |
| 6201 | read_only | if SIGNAL_NEXT_CYCLE_VALIDATION_ENABLED and symbol and self._signal_redis: |
| 6208 | write_signal | #   We keep validation for normal OPEN_RISK signals, but allow immediate publish |
| 6211 | read_only | src_tag = str(payload.get("source") or payload.get("source_tag") or "").lower() |
| 6212 | read_only | urgency_tag = str(payload.get("urgency") or "").upper() |
| 6219 | read_only | or bool(payload.get("is_flash_move")) |
| 6220 | read_only | or float(payload.get("flash_move_pct", 0.0) or 0.0) != 0.0 |
| 6224 | read_only | if action_category == "HEDGE" and not payload.get("bypass_validation"): |
| 6226 | read_only | elif is_flash_hedge and not payload.get("bypass_validation"): |
| 6232 | read_only | payload.get("bypass_validation") |
| 6233 | read_only | or payload.get("force_execute") |
| 6234 | read_only | or payload.get("gating_override") |
| 6262 | read_only | pnl_pct = float((position_info or {}).get("pnl_pct", 0) or 0) |
| 6269 | read_only | acct = payload.get("account_id") or payload.get("account") or payload.get("target_account_id") or "global" |
| 6274 | write_metric | # we will force a publish on the next eligible cycle (min_age satisfied), |
| 6281 | read_only | raw = self._signal_redis.get(pending_key) |
| 6294 | write_metric | # First sighting: stage and return (no publish this cycle) |
| 6302 | read_only | raw_attempt = self._signal_redis.get(attempt_key) |
| 6309 | read_only | meta["attempts"] = int(meta.get("attempts", 0) or 0) + 1 |
| 6310 | read_only | meta["first_ts"] = float(meta.get("first_ts", now) or now) |
| 6315 | read_only | self._signal_redis.setex( |
| 6324 | read_only | self._signal_redis.setex( |
| 6342 | write_metric | self._publish_skip_event( |
| 6354 | write_metric | self._maybe_publish_recovery_reduction( |
| 6358 | read_only | blocked_side=str(payload.get("side") or ""), |
| 6361 | read_only | needed_margin_usd=float(payload.get("margin_usd") or 0.0), |
| 6369 | read_only | if str(pending.get("action_name") or "") != str(action_name): |
| 6371 | read_only | self._signal_redis.setex( |
| 6382 | read_only | "replaced": str(pending.get("action_name") or ""), |
| 6390 | write_metric | self._publish_skip_event( |
| 6393 | read_only | f"pending_action={pending.get('action_name')} -> {action_name}", |
| 6397 | read_only | logger.info(f"⏳ [NEXT_CYCLE_VALIDATE_RESET] {acct} {symbol} {pending.get('action_name')} -> {action_name}") |
| 6400 | read_only | created_ts = float(pending.get("created_ts", now) or now) |
| 6404 | write_metric | self._publish_skip_event( |
| 6414 | write_risk_state | # If the same OPEN_RISK has been staged repeatedly, force a validate/publish attempt |
| 6420 | read_only | raw_attempt = self._signal_redis.get(attempt_key) |
| 6425 | read_only | attempts = int(meta.get("attempts", 0) or 0) |
| 6426 | read_only | first_ts = float(meta.get("first_ts", now) or now) |
| 6428 | write_signal | # if we've been stuck validating longer than 2×TTL, force publish attempt. |
| 6431 | read_only | if waited_s >= max_wait_s and not payload.get("validated_next_cycle"): |
| 6432 | write_checkpoint_metadata | payload["_validation_force_publish"] = True |
| 6443 | read_only | snap = float(micro.get("snapback_score", 0.0) or 0.0) |
| 6444 | write_metric | # Note: analyze_market_microstructure publishes `market_maker_score` (0..1). |
| 6447 | read_only | micro.get("market_maker_score", None) |
| 6448 | read_only | or micro.get("mm_manipulation_score", None) |
| 6451 | read_only | is_flash = bool(micro.get("is_flash_move", False)) |
| 6465 | read_only | self._signal_redis.setex( |
| 6473 | write_metric | self._publish_skip_event( |
| 6476 | read_only | str(pending.get("delay_reason") or "pressure >= conf"), |
| 6485 | write_metric | # Validated: allow downstream gates and clear pending AFTER successful publish. |
| 6495 | read_only | 'count': 1 if position_info and position_info.get('has_position') else 0, |
| 6496 | read_only | 'side': position_info.get('side') if position_info else None, |
| 6499 | write_signal | should_publish, coord_reason = self.signal_coordinator.should_publish_signal( |
| 6507 | write_metric | if not should_publish: |
| 6509 | write_signal | self._publish_skip_event(payload, "SIGNAL_COORDINATOR_BLOCK", coord_reason) |
| 6512 | read_only | from utils.redis_client import get_redis_client |
| 6513 | read_only | get_redis_client().hincrby('trainer:critical_fixes:stats', 'signals_blocked', 1) |
| 6521 | read_only | from utils.redis_client import get_redis_client |
| 6522 | read_only | get_redis_client().hincrby('trainer:critical_fixes:stats', 'signals_processed', 1) |
| 6533 | read_only | state_manager = get_signal_state_manager(getattr(self, '_signal_redis', None)) |
| 6538 | read_only | _acct_scope = payload.get("account_id") or payload.get("account") or payload.get("target_account_id") |
| 6561 | write_signal | self._publish_skip_event(payload, "SIGNAL_STATE_BLOCK", dedup_reason) |
| 6595 | read_only | # Get Redis client |
| 6596 | read_only | redis_client = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 6597 | read_only | if not redis_client: |
| 6599 | read_only | from utils.redis_client import get_redis |
| 6600 | read_only | redis_client = get_redis() |
| 6602 | read_only | redis_client = None |
| 6604 | read_only | if redis_client: |
| 6610 | read_only | entry_price = float(payload.get('trigger_price') or payload.get('entry_price') or |
| 6611 | read_only | payload.get('price') or current_price or 0) |
| 6630 | write_checkpoint_metadata | self._publish_skip_event(payload, "SMART_ENTRY_WAIT_FOR_PULLBACK", reason_str) |
| 6637 | write_checkpoint_metadata | self._publish_skip_event(payload, "SMART_ENTRY_COOLDOWN", reason_str) |
| 6650 | read_only | orig_margin = float(payload.get('margin_usd', 0) or 0) |
| 6651 | read_only | orig_notional = float(payload.get('notional_usd', 0) or 0) |
| 6689 | read_only | orig_margin = float(payload.get('margin_usd', 0) or 0) |
| 6690 | read_only | orig_notional = float(payload.get('notional_usd', 0) or 0) |
| 6707 | read_only | orig_margin = float(payload.get('margin_usd', 0) or 0) |
| 6708 | read_only | orig_notional = float(payload.get('notional_usd', 0) or 0) |
| 6733 | read_only | redis_client = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 6734 | read_only | if redis_client: |
| 6739 | read_only | has_hedge = (redis_client.exists(hedge_key_primary) or |
| 6740 | read_only | redis_client.exists(hedge_key_asjad)) |
| 6746 | read_only | hedge_intel = get_hedge_intelligence_engine(redis_client) |
| 6749 | read_only | current_roe = float(payload.get('current_roe_pct') or |
| 6750 | read_only | payload.get('roe_pct') or |
| 6751 | read_only | payload.get('pnl_pct', 0) or 0) |
| 6752 | read_only | hedge_pnl = float(payload.get('hedge_pnl_pct', 0) or 0) |
| 6767 | write_metric | self._publish_skip_event( |
| 6781 | write_checkpoint_metadata | self._publish_skip_event(payload, "HEDGE_PROTECTION_BLOCK", |
| 6797 | read_only | fees_today = self._perf_metrics.get('fees_today', 0.0) |
| 6801 | write_checkpoint_metadata | self._publish_skip_event(payload, "FEE_BUDGET_EXCEEDED", |
| 6806 | read_only | notional = float(payload.get('notional_usd') or payload.get('notional', 0) or 0) |
| 6811 | write_checkpoint_metadata | self._publish_skip_event(payload, "FEE_BUDGET_EXCEEDED", |
| 6828 | read_only | notional = float(payload.get('notional_usd') or payload.get('notional', 0) or 0) |
| 6829 | read_only | conf = float(payload.get('confidence') or payload.get('model_confidence') or 0.0) |
| 6830 | read_only | tf = payload.get('timeframe', '5m') |
| 6841 | read_only | # Get Redis client for adaptive gate |
| 6842 | read_only | redis_client = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 6843 | read_only | if not redis_client: |
| 6845 | read_only | from utils.redis_client import get_redis |
| 6846 | read_only | redis_client = get_redis() |
| 6848 | read_only | redis_client = None |
| 6850 | read_only | adaptive_gate = get_adaptive_edge_gate(redis_client=redis_client) |
| 6867 | read_only | (float((_st or {}).get("available_margin_usd", 0.0) or 0.0) / float((_st or {}).get("equity_usd", 0.0) or 0.0)) |
| 6868 | read_only | if float((_st or {}).get("equity_usd", 0.0) or 0.0) > 0.0 |
| 6870 | read_only | (float(payload.get("available_margin", 0.0) or 0.0) / float(payload.get("portfolio_balance", 0.0) or 0.0)) |
| 6871 | read_only | if float(payload.get("portfolio_balance", 0.0) or 0.0) > 0.0 |
| 6875 | read_only | ))(str(payload.get("account_id") or payload.get("account") or payload.get("target_account_id") or "").strip().lower()) |
| 6881 | write_checkpoint_metadata | self._publish_skip_event(payload, "ADAPTIVE_EDGE_BLOCK", reason) |
| 6909 | read_only | 1 for t in self._perf_metrics.get('trade_history', []) |
| 6910 | read_only | if t.get('symbol') == symbol and t.get('ts', 0) > one_hour_ago |
| 6916 | write_checkpoint_metadata | self._publish_skip_event(payload, "TRADE_THROTTLE_BLOCK", |
| 6941 | write_checkpoint_metadata | self._publish_skip_event(payload, "FEE_RATIO_BLOCK", reason) |
| 6968 | read_only | should_block, block_reason = safe_mode_block(payload.get("action") or payload.get("action_name") or "UNKNOWN") |
| 6970 | read_only | logger.warning(f"⛔ [SAFE_MODE_BLOCK] {payload.get('symbol')} {payload.get('action')}: {block_reason}") |
| 6971 | write_checkpoint_metadata | self._publish_skip_event(payload, "SAFE_MODE_NO_CHECKPOINT", block_reason) |
| 6982 | read_only | tf = payload.get('timeframe', '5m') |
| 6985 | read_only | if monitor.is_entry_action(str(payload.get('action') or payload.get('action_name') or '')): |
| 6987 | write_checkpoint_metadata | self._publish_skip_event(payload, "FEATURE_HEALTH_BLOCK", cached_report.block_reason) |
| 6999 | write_metric | # If any are missing/stale -> FAIL-CLOSED (do not publish hedge). |
| 7001 | read_only | if bool(payload.get("_trainer_hedge_requires_data")) and action_type in {"open", "flip", "increase"}: |
| 7003 | read_only | redis_client = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 7004 | read_only | if not redis_client and hasattr(self, "config"): |
| 7005 | read_only | redis_client = getattr(self.config, "redis_client", None) |
| 7006 | read_only | if not redis_client: |
| 7007 | read_only | from utils.redis_client import get_redis  # type: ignore |
| 7008 | read_only | redis_client = get_redis() |
| 7011 | read_only | sym_u = str(symbol or payload.get("symbol") or "").upper().strip() |
| 7012 | read_only | tf_u = str(payload.get("timeframe") or payload.get("tf") or "5m").lower().strip() |
| 7015 | read_only | # not a real Redis key. Fall back to "5m" for data-quality checks. |
| 7023 | read_only | uf = redis_client.hgetall(f"unified_features:{sym_u}:{tf_u}") or {} |
| 7032 | read_only | raw = uf.get("data") |
| 7040 | read_only | if isinstance(obj.get(k), dict): |
| 7052 | read_only | min_feat = int(payload.get("_trainer_hedge_min_feature_keys") or 200) |
| 7059 | read_only | ms = redis_client.hgetall(f"msnap:coinapi_wsds:{sym_u}") or {} |
| 7068 | read_only | ts_ms = int(float(ms.get("updated_ts_ms", 0) or 0)) |
| 7073 | read_only | max_ms_age = int(payload.get("_trainer_hedge_max_msnap_age_ms") or 8000) |
| 7080 | read_only | liq = redis_client.hgetall(f"binance_liq:{sym_u}") or {} |
| 7090 | write_metric | # Require freshness, but allow 0.0 levels when there are no events (engine still publishes defaults). |
| 7095 | read_only | def _uf_get(k: str, default=None): |
| 7097 | read_only | v = (uf or {}).get(k, default) |
| 7106 | read_only | liq_updated_ts = int(float(_uf_get("liquidation_updated_ts", 0) or 0)) |
| 7112 | read_only | max_liq_engine_age = int(payload.get("_trainer_hedge_max_liq_engine_age_ms") or 60000) |
| 7120 | read_only | levels_json = _uf_get("liquidation_levels_json", "") or "" |
| 7121 | read_only | liq_source = _uf_get("liquidation_source", "") or "" |
| 7129 | read_only | ca = redis_client.hgetall(f"[REDACTED]:{sym_u}") or {} |
| 7132 | read_only | fr = (ca or {}).get("funding_rate") |
| 7133 | read_only | oi = (ca or {}).get("open_interest") |
| 7141 | write_checkpoint_metadata | self._publish_skip_event(payload, "TRAINER_HEDGE_DATA_MISSING", detail) |
| 7150 | write_checkpoint_metadata | self._publish_skip_event(payload, "TRAINER_HEDGE_DATA_ERROR", str(dh_err)[:180]) |
| 7159 | read_only | symbol = payload.get('symbol') |
| 7160 | read_only | tf = payload.get('timeframe') or payload.get('tf') or '5m' |
| 7161 | read_only | action_name = payload.get('action_name') or payload.get('action') or '' |
| 7162 | read_only | action_category = payload.get('action_category') or get_action_category(action_name) |
| 7167 | read_only | redis_client = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 7168 | read_only | if not redis_client and hasattr(self, 'config'): |
| 7169 | read_only | redis_client = getattr(self.config, 'redis_client', None) |
| 7170 | read_only | if not redis_client: |
| 7172 | read_only | from utils.redis_client import get_redis |
| 7173 | read_only | redis_client = get_redis() |
| 7175 | read_only | logger.warning("[MICROSTRUCTURE] Cannot get Redis client for health check") |
| 7188 | read_only | if redis_client: |
| 7191 | read_only | promotion_ctrl = get_promotion_controller(redis_client=redis_client) |
| 7198 | read_only | microstructure_tier = micro_details.get('tier', 'unknown') |
| 7200 | read_only | if micro_details.get('warning'): |
| 7202 | read_only | if micro_details.get('reason'): |
| 7213 | read_only | msnap_data = redis_client.hgetall(f"msnap:coinapi_wsds:{symbol}") |
| 7217 | read_only | bookticker_raw = redis_client.get(f"orderbook:top:{symbol}") |
| 7223 | read_only | 'best_bid_px': str(bookticker.get('bid', 0)), |
| 7224 | read_only | 'best_ask_px': str(bookticker.get('ask', 0)), |
| 7225 | read_only | 'mid_px': str(bookticker.get('mid_px', 0)), |
| 7226 | read_only | 'imbalance_5': str(bookticker.get('imbalance', 0)), |
| 7227 | read_only | 'updated_ts_ms': str(bookticker.get('updated_ts_ms', 0)), |
| 7234 | read_only | logger.info(f"[MICRO_FALLBACK_DATA] {symbol} / using [REDACTED] bookticker / age={(int(time.time()*1000) - int(bookticker.get('updated_ts_ms', 0)))/1000:.1f}s") |
| 7243 | read_only | spoof_score = float(msnap_data.get('spoof_score', 0) or 0) |
| 7248 | read_only | fast_move_instant = float(msnap_data.get('fast_move_score', 0) or 0) |
| 7249 | read_only | fast_move_max_1m = float(msnap_data.get('fast_move_max_1m', 0) or 0) |
| 7250 | read_only | churn_score = float(msnap_data.get('churn_score', 0) or 0) |
| 7251 | read_only | snapback_score = float(msnap_data.get('snapback_score', 0) or 0) |
| 7252 | read_only | imbalance_5 = float(msnap_data.get('imbalance_5', 0) or 0) |
| 7283 | read_only | if not bool(payload.get("recovery_intent")): |
| 7286 | read_only | account_id = payload.get("account_id") or payload.get("account") or payload.get("accountId") |
| 7295 | read_only | rt_raw = redis_client.get(f"price:realtime:{symbol}") if redis_client else None |
| 7304 | read_only | ts_ms = int(float(rt.get("ts_ms", 0) or rt.get("timestamp_ms", 0) or 0)) |
| 7311 | read_only | sev = float(payload.get("urc_sev", 0.0) or 0.0) |
| 7321 | read_only | rev_rank = float(payload.get("urc_reversal_rank", 0.0) or 0.0) |
| 7333 | read_only | long_raw = redis_client.hget(pos_key, f"{sym_u}:LONG") |
| 7334 | read_only | short_raw = redis_client.hget(pos_key, f"{sym_u}:SHORT") |
| 7344 | read_only | if p.get("has_position") is False: |
| 7346 | read_only | return abs(float(p.get("size", 0) or 0.0)) > 1e-12 |
| 7354 | read_only | eq_raw = redis_client.get(f"portfolio:equity:{account_id}") |
| 7362 | read_only | avail_margin = float(eq.get("available_margin_usd", 0.0) or 0.0) |
| 7366 | read_only | add_margin = float(payload.get("margin_usd", 0.0) or 0.0) |
| 7395 | write_checkpoint_metadata | self._publish_skip_event(payload, "MICROSTRUCTURE_FAIL_CLOSED", "Microstructure feed unhealthy") |
| 7407 | write_checkpoint_metadata | self._publish_skip_event(payload, "MICROSTRUCTURE_FAIL_CLOSED", "Microstructure feed unhealthy") |
| 7412 | write_risk_state | # generally unreachable. Keep as a defensive guard, but DO NOT return early (must continue to publish). |
| 7461 | read_only | r = float(micro.get("ret_5s", 0.0) or 0.0) or float(micro.get("ret_15s", 0.0) or 0.0) |
| 7487 | read_only | conf = float(payload.get('confidence') or payload.get('model_confidence') or 0.0) |
| 7508 | read_only | or (action_category == "HEDGE" and bool(payload.get("_trainer_hedge_requires_data"))) |
| 7529 | read_only | if 'position_size_pct' in payload and payload.get('position_size_pct') is not None: |
| 7531 | read_only | original_size = float(payload.get('position_size_pct') or 0.0) |
| 7538 | read_only | if k in payload and payload.get(k) is not None: |
| 7540 | read_only | payload[k] = max(0.0, float(payload.get(k) or 0.0) * scale) |
| 7556 | write_checkpoint_metadata | self._publish_skip_event(payload, "MICRO_OVERLAY_BLOCK", detail) |
| 7567 | read_only | str(payload.get('action') or payload.get('action_name') or ''), |
| 7572 | write_checkpoint_metadata | self._publish_skip_event(payload, "WARMUP_BLOCK", warmup_reason) |
| 7585 | read_only | conf = float(payload.get('confidence') or payload.get('model_confidence') or 0.0) |
| 7603 | write_checkpoint_metadata | self._publish_skip_event(payload, "OPEN_RISK_BLOCK", f"{tf} is bias-only") |
| 7607 | write_checkpoint_metadata | self._publish_skip_event(payload, "OPEN_RISK_BLOCK", f"{tf} is execution-gate only") |
| 7611 | write_checkpoint_metadata | self._publish_skip_event(payload, "OPEN_RISK_BLOCK", f"{tf} is protective-only") |
| 7626 | read_only | liq_total = abs(float(threshold_meta.get('liq_long', 0.0) or 0.0)) + abs(float(threshold_meta.get('liq_short', 0.0) or 0.0)) |
| 7627 | read_only | liq_imb = abs(float(threshold_meta.get('liq_long', 0.0) or 0.0) - float(threshold_meta.get('liq_short', 0.0) or 0.0)) / max(liq_total, 1.0) if liq_total > 0 else 0.0 |
| 7630 | read_only | f"quality={threshold_meta.get('quality_score', 0.0):.2f} spoof={threshold_meta.get('spoof_score', 0.0):.2f} " |
| 7631 | read_only | f"fast={threshold_meta.get('fast_move_score', 0.0):.2f} liq_imb={liq_imb:.2f}" |
| 7639 | write_checkpoint_metadata | self._publish_skip_event(payload, "CONTEXTUAL_CONF_BLOCK", |
| 7646 | read_only | stack = trainer_ref._tf_stack.get(symbol, {}) |
| 7647 | read_only | bias = stack.get('bias') |
| 7663 | write_checkpoint_metadata | self._publish_skip_event(payload, "BIAS_REQUIRED_BLOCK", |
| 7674 | write_checkpoint_metadata | self._publish_skip_event(payload, "HEDGE_BLOCK_TF_ROLE", f"{tf} is protective-only") |
| 7689 | read_only | if pos.get('has_position'): |
| 7692 | read_only | position_age_sec = pos.get('age_seconds', 0) or 0 |
| 7698 | write_checkpoint_metadata | self._publish_skip_event(payload, "DECREASE_AGE_BLOCK", |
| 7703 | read_only | pnl_pct = pos.get('pnl_pct', 0) or 0 |
| 7714 | write_checkpoint_metadata | self._publish_skip_event(payload, "DECREASE_PNL_BLOCK", |
| 7727 | read_only | stack = trainer_ref._tf_stack.get(symbol, {}) |
| 7728 | read_only | confirm = stack.get('confirm')  # 1h |
| 7729 | read_only | bias = stack.get('bias')  # 4h |
| 7732 | read_only | if confirm and 'DECREASE' in str(confirm.get('action', '')).upper(): |
| 7736 | read_only | pos_side = pos.get('side', '').upper() |
| 7737 | read_only | bias_dir = bias.get('direction', '') |
| 7745 | write_checkpoint_metadata | self._publish_skip_event(payload, "DECREASE_HTF_BLOCK", |
| 7764 | read_only | stack = trainer_ref._tf_stack.get(symbol, {}) |
| 7765 | read_only | bias = stack.get('bias') |
| 7798 | write_checkpoint_metadata | self._publish_skip_event(payload, "COUNTER_TREND_BLOCK", |
| 7806 | read_only | action_str = str(payload.get('action') or payload.get('action_name') or '').upper() |
| 7811 | read_only | # Get current position PnL percentage - query FRESH from Redis |
| 7815 | read_only | # PRIORITY 1: Query Redis directly for fresh position data (not stale cached) |
| 7816 | read_only | redis_client = getattr(self, 'redis', None) or getattr(self, '_signal_redis', None) |
| 7817 | read_only | if not redis_client: |
| 7819 | read_only | from utils.redis_client import get_redis |
| 7820 | read_only | redis_client = get_redis() |
| 7824 | read_only | if redis_client: |
| 7828 | read_only | acct = str(payload.get("account_id") or payload.get("account") or "").strip().lower() |
| 7842 | read_only | pos_data = redis_client.hget(positions_key, f"{symbol}:{action_side}") |
| 7849 | read_only | pos.get('pnl_pct', 0) or |
| 7850 | read_only | pos.get('pnl_percentage', 0) or |
| 7851 | read_only | pos.get('roi_pct', 0) or 0 |
| 7863 | read_only | pos_hash = redis_client.hgetall(positions_key) |
| 7876 | read_only | pos.get('pnl_pct', 0) or |
| 7877 | read_only | pos.get('pnl_percentage', 0) or |
| 7878 | read_only | pos.get('roi_pct', 0) or 0 |
| 7898 | read_only | pos = (self._real_positions.get(side_key) if side_key else None) or \ |
| 7899 | read_only | self._real_positions.get(f"{side_key}_primary") if side_key else None or \ |
| 7900 | read_only | self._real_positions.get(symbol) or \ |
| 7901 | read_only | self._real_positions.get(f"{symbol}_primary") |
| 7904 | read_only | pos.get('pnl_percentage', 0) or |
| 7905 | read_only | pos.get('pnl_pct', 0) or |
| 7906 | read_only | pos.get('roi_pct', 0) or 0 |
| 7914 | read_only | pos.get('pnl_percentage', 0) or |
| 7915 | read_only | pos.get('pnl_pct', 0) or |
| 7916 | read_only | pos.get('roi_pct', 0) or 0 |
| 7921 | read_only | current_pnl_pct = float(payload.get('pnl_pct', 0) or payload.get('roi_pct', 0) or 0) |
| 7931 | read_only | float(micro.get("market_maker_score", 0.0) or 0.0), |
| 7932 | read_only | float(micro.get("snapback_score", 0.0) or 0.0), |
| 7933 | read_only | float(micro.get("fast_move_persist", 0.0) or 0.0), |
| 7951 | write_checkpoint_metadata | self._publish_skip_event(payload, "FEE_AWARE_BLOCK", block_reason) |
| 7962 | read_only | position_size = abs(float(pos.get('size', 0) or pos.get('positionAmt', 0) or pos.get('qty', 0) or 0)) |
| 7963 | read_only | position_side = pos.get('side', '').upper() |
| 7970 | read_only | # Check both accounts for this symbol via Redis |
| 7973 | read_only | if redis_client: |
| 7976 | read_only | all_keys = redis_client.keys(f"{account_key}*{symbol}*") if account_key.startswith('wma:') else [] |
| 7980 | read_only | pos_raw = redis_client.get(k) if redis_client.type(k) == b'string' else None |
| 7985 | read_only | size = abs(float(pos_check.get('size', 0) or pos_check.get('positionAmt', 0) or 0)) |
| 7994 | read_only | pos_data = redis_client.hget(account_key, symbol) |
| 7999 | read_only | size = abs(float(pos_check.get('size', 0) or pos_check.get('positionAmt', 0) or 0)) |
| 8015 | write_checkpoint_metadata | self._publish_skip_event(payload, "NO_POSITION_BLOCK", block_reason) |
| 8039 | read_only | if redis_client: |
| 8044 | read_only | pos_data = redis_client.hget(pos_key, side_field) |
| 8048 | read_only | pos_side = pos_check.get('side', '').upper() |
| 8049 | read_only | pos_size = abs(float(pos_check.get('size', 0) or pos_check.get('positionAmt', 0) or 0)) |
| 8060 | write_checkpoint_metadata | self._publish_skip_event(payload, "SIDE_MISMATCH_BLOCK", block_reason) |
| 8076 | read_only | if redis_client: |
| 8077 | read_only | acct_hint = payload.get("account_id") or payload.get("account") or payload.get("target_account_id") |
| 8084 | read_only | pos_data = redis_client.hget(pos_key, side_field) |
| 8089 | read_only | pos_side = str(pos_check.get("side") or expected_side).upper() |
| 8090 | read_only | pos_size = abs(float(pos_check.get('size', 0) or pos_check.get('positionAmt', 0) or 0)) |
| 8101 | write_checkpoint_metadata | self._publish_skip_event(payload, "SIDE_MISMATCH_BLOCK", block_reason) |
| 8128 | write_metric | # This is the central chokepoint - ALL publish paths go through here |
| 8137 | read_only | payload.get("account_id") or payload.get("account") or payload.get("target_account_id") |
| 8141 | write_metric | # Prefer redis available on this publisher; fall back to trainer redis when running inside PPO. |
| 8142 | read_only | redis_client = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 8143 | read_only | if redis_client is None: |
| 8145 | read_only | redis_client = getattr(trainer_ref, "redis", None) if trainer_ref is not None else None |
| 8149 | read_only | if not redis_client: |
| 8156 | read_only | _t = redis_client.type(ck) |
| 8169 | read_only | raw = redis_client.hget(ck, f"{symbol}:{side}") |
| 8184 | read_only | if "has_position" in pos and not bool(pos.get("has_position")): |
| 8189 | read_only | sz = abs(float(pos.get("size", 0) or pos.get("positionAmt", 0) or pos.get("qty", 0) or 0)) |
| 8213 | read_only | action_str = str(payload.get('action') or payload.get('action_name') or 'UNKNOWN').upper() |
| 8229 | read_only | f"conf={payload.get('confidence', 0):.3f} / source={payload.get('source', 'unknown')}" |
| 8231 | write_checkpoint_metadata | self._publish_skip_event(payload, "ONE_MIN_FLAT_ENTRY_BLOCK", |
| 8241 | write_checkpoint_metadata | # IMPORTANT: If a payload already specifies an `account_id`, we only publish |
| 8244 | read_only | requested_account_id = payload.get("account_id") or payload.get("account") or payload.get("target_account_id") |
| 8257 | write_checkpoint_metadata | logger.warning(f"[PUBLISH] Unknown account_id={req} in payload; publishing to all accounts") |
| 8279 | read_only | act_u = str(payload.get("action_name") or payload.get("action") or "").upper() |
| 8286 | read_only | acct0 = payload.get("account_id") or (target_streams[0][0] if target_streams else None) |
| 8288 | read_only | acct0 = payload.get("account_id") |
| 8291 | write_metric | # Use trader-published positions as the source of truth |
| 8304 | read_only | p0 = tp.get(k) or {} |
| 8306 | read_only | if abs(float(p0.get("size", 0) or 0.0)) > 0.0: |
| 8319 | read_only | p0 = tp.get(k) or {} |
| 8321 | read_only | has_main_leg = abs(float(p0.get("size", 0) or 0.0)) > 0.0 |
| 8331 | write_checkpoint_metadata | self._publish_skip_event(payload, "HEDGE_FROM_FLAT_BLOCK", detail) |
| 8362 | read_only | redis_client = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 8363 | read_only | if not redis_client or not account_id or not side: |
| 8365 | read_only | raw = redis_client.hget(f"portfolio:positions:{account_id}", f"{symbol}:{side}") |
| 8372 | read_only | return float(pos.get("pnl_pct", 0) or pos.get("unrealized_pnl_pct", 0) or 0) |
| 8379 | read_only | _no_loss_bypass_recovery = bool(payload.get("recovery_rebalance")) and bool(RECOVERY_BYPASS_NO_LOSS_EXIT_GUARD) |
| 8386 | read_only | _signal_conf = float(payload.get("confidence") or payload.get("model_confidence") or 0) |
| 8398 | read_only | action_u = str(action_name or payload.get("action") or "").upper() |
| 8402 | write_metric | # hedge_intent flags (we've seen that happen through legacy publish paths). |
| 8428 | read_only | _ate = get_adaptive_engine(redis_client=self.redis) |
| 8430 | read_only | _ate_lev = float(payload.get("leverage", 20) or 20) |
| 8468 | write_signal | f"[NO_LOSS_GUARD] {symbol} blocking publish {action_u} for account={aid} " |
| 8474 | write_metric | self._publish_skip_event( |
| 8489 | read_only | agg_pnl = float(pos.get("pnl_pct", 0) or 0) |
| 8492 | write_signal | f"[NO_LOSS_GUARD] {symbol} blocking publish {action_u} (agg pnl={agg_pnl:+.2f}%)" |
| 8494 | write_metric | self._publish_skip_event( |
| 8531 | read_only | raw_exit = self._signal_redis.get(f"wma:last_exit:{aid}:{symbol}") |
| 8536 | read_only | prev_sides = [str(s).upper() for s in (exit_info.get("prev_sides") or [])] |
| 8557 | read_only | conf_val = payload.get("confidence") |
| 8559 | read_only | conf_val = payload.get("model_confidence", 0.0) |
| 8565 | read_only | fastlane_hint = bool(payload.get("fastlane")) or bool(payload.get("is_flash_move")) or float(payload.get("flash_move_pct", 0.0) or 0.0) != 0.0 |
| 8570 | read_only | last_px = float(exit_info.get("exit_mark_price") or 0.0) |
| 8577 | read_only | v = payload.get(k) |
| 8588 | read_only | feat = self._signal_redis.hgetall(f"features:unified:{symbol}:1m") or {} |
| 8591 | read_only | vv = feat.get(kk) |
| 8612 | write_checkpoint_metadata | self._publish_skip_event(payload, "REENTRY_HYSTERESIS_BLOCK", msg) |
| 8619 | read_only | symbol = payload.get("symbol") |
| 8625 | read_only | last_flip_ms = self._signal_redis.get(cooldown_key) |
| 8633 | write_checkpoint_metadata | self._publish_skip_event(payload, "TRAINER_FLIP_COOLDOWN", f"Last flip {age_sec:.0f}s ago") |
| 8636 | read_only | self._signal_redis.setex(cooldown_key, 3600, str(now_ms))  # 1hr TTL |
| 8647 | read_only | symbol = payload.get("symbol", "") |
| 8648 | read_only | action_name = str(payload.get("action_name") or payload.get("action") or "").upper() |
| 8660 | read_only | last_close_ms = self._signal_redis.get(last_close_key) |
| 8672 | read_only | conf = float(payload.get("confidence") or payload.get("model_confidence") or 0) |
| 8678 | write_checkpoint_metadata | self._publish_skip_event(payload, "REVERSAL_CONFIRMATION_REQUIRED", |
| 8688 | read_only | symbol = payload.get("symbol", "") |
| 8689 | read_only | action_name = str(payload.get("action_name") or payload.get("action") or "").upper() |
| 8695 | read_only | self._signal_redis.setex(close_key, 300, str(int(time.time() * 1000)))  # 5min TTL |
| 8702 | read_only | self._signal_redis.setex(close_key, 300, str(int(time.time() * 1000)))  # 5min TTL |
| 8708 | read_only | action_name = str(payload.get("action_name") or payload.get("predicted_action") or payload.get("action") or "UNKNOWN").upper() |
| 8709 | read_only | symbol = payload.get("symbol") |
| 8715 | read_only | last_action_ms = self._signal_redis.get(dedupe_key) |
| 8723 | write_signal | self._publish_skip_event(payload, "TRAINER_ACTION_DEDUPE", f"Duplicate {action_name} within {age_sec:.0f}s") |
| 8726 | read_only | self._signal_redis.setex(dedupe_key, 120, str(now_ms))  # 2min TTL |
| 8730 | write_signal | # SIGNAL VALIDATOR: Check historical performance before publishing |
| 8733 | read_only | symbol = payload.get('symbol') |
| 8734 | read_only | action = str(payload.get('action') or payload.get('action_name') or '').upper() |
| 8735 | read_only | confidence = float(payload.get('confidence') or payload.get('model_confidence') or 0) |
| 8741 | read_only | "timeframe": payload.get("timeframe"), |
| 8742 | read_only | "action_category": payload.get("action_category"), |
| 8753 | write_checkpoint_metadata | self._publish_skip_event(payload, _vcode, validator_reason) |
| 8768 | read_only | symbol = payload.get('symbol') |
| 8770 | read_only | action_name = str(payload.get('action_name') or payload.get('predicted_action') or payload.get('action') or '').upper() |
| 8773 | read_only | conf_val = payload.get('confidence') |
| 8775 | read_only | conf_val = payload.get('model_confidence') |
| 8777 | read_only | conf_val = payload.get('ppo_confidence', 0)  # Fallback to PPO confidence |
| 8785 | read_only | margin_required = float(payload.get('margin_usd') or 0.0) |
| 8790 | read_only | notional = float(payload.get('notional_usd') or 0.0) |
| 8794 | read_only | lev = float(payload.get('leverage') or payload.get('recommended_leverage') or 0.0) |
| 8804 | read_only | f"payload_keys={list(payload.keys())}, payload_conf={payload.get('confidence')}, payload_model_conf={payload.get('model_confidence')}") |
| 8817 | read_only | is_hedge = bool(payload.get("hedge_intent")) or act_u.startswith(("OPEN_HEDGE_", "ADD_HEDGE_")) or ( |
| 8818 | read_only | str(payload.get("action_category") or "").upper() == "HEDGE" |
| 8826 | read_only | pos_side = pos_data.get('side', '').upper() if isinstance(pos_data, dict) else '' |
| 8841 | read_only | redis_client=self._signal_redis, |
| 8855 | read_only | src = str(payload.get("source") or "").strip().lower() |
| 8856 | read_only | cat = str(payload.get("action_category") or action_category or "").strip().upper() |
| 8857 | read_only | allow_rebalance_bypass = bool(payload.get("auto_rebalance")) and (src == "portfolio_recovery_allocator" or cat in {"OPEN_RISK", "RECOVERY"}) |
| 8872 | write_metric | # Continue publishing (trader will close profit-only slot/margin before opening). |
| 8887 | write_checkpoint_metadata | self._publish_skip_event(payload, block_reason, decision.block_detail) |
| 8906 | read_only | symbol = payload.get("symbol", "?") |
| 8907 | read_only | action = payload.get("action_name") or payload.get("action") or "?" |
| 8911 | write_checkpoint_metadata | self._publish_skip_event(payload, "CONTRACT_BLOCK", reason or "contract validation failed") |
| 8914 | read_only | # Safety check: Ensure Redis client is available |
| 8915 | read_only | if self._signal_redis is None: |
| 8917 | read_only | from utils.redis_client import get_redis |
| 8918 | read_only | self._signal_redis = get_redis() |
| 8919 | read_only | if self._signal_redis: |
| 8920 | read_only | self._signal_redis.ping() |
| 8921 | write_metric | logger.info("🔗 [PUBLISH] Reinitialized Redis client") |
| 8923 | write_metric | logger.error("❌ [PUBLISH] Cannot publish - Redis client is None") |
| 8925 | read_only | except Exception as redis_err: |
| 8926 | write_metric | logger.error(f"❌ [PUBLISH] Cannot publish - Redis unavailable: {redis_err}") |
| 8930 | write_metric | # PUBLISH_ATTEMPT LOG (Task D from audit) |
| 8932 | read_only | symbol = built.get("symbol", "?") |
| 8933 | read_only | tf = built.get("timeframe", "?") |
| 8934 | read_only | action = built.get("action") or built.get("action_name") or "?" |
| 8935 | read_only | conf = built.get("confidence", 0) |
| 8936 | read_only | margin_usd = built.get("margin_usd", 0) |
| 8937 | read_only | notional_usd = built.get("notional_usd", 0) |
| 8938 | read_only | lev = built.get("leverage", 0) |
| 8940 | write_signal | f"PUBLISH_ATTEMPT / {symbol} / {tf} / {action} / conf={conf:.3f} / " |
| 8945 | write_metric | # Publish to all target streams (per-account or single canonical) |
| 8947 | read_only | maxlen = getattr(self.main_config, "SIGNAL_STREAM_MAXLEN", 5000) |
| 8969 | read_only | # HEDGE LOCK (Redis-backed, cross-process) |
| 8974 | read_only | symbol_out = built_out.get("symbol") |
| 8975 | read_only | action_out = str(built_out.get("action") or built_out.get("action_name") or "").upper() |
| 8980 | read_only | raw_lock = self._signal_redis.get(lock_key) |
| 8985 | read_only | hedge_side = str(lock_payload.get("hedge_side") or "").upper() |
| 8991 | read_only | src = str(built_out.get("source") or "").lower() |
| 8992 | read_only | is_profit_intent = bool(built_out.get("profit_intent")) or src == "proactive_profit_scanner" |
| 8993 | read_only | close_fraction = float(built_out.get("close_fraction", 1.0) or 1.0) |
| 9001 | read_only | leg_role = str(built_out.get("leg_role") or "").upper() |
| 9003 | read_only | built_out.get("roe_pct") |
| 9004 | read_only | or built_out.get("current_roe_pct") |
| 9005 | read_only | or built_out.get("pnl_pct") |
| 9008 | read_only | main_roe = float(built_out.get("main_roe_pct") or lock_payload.get("main_roe_pct") or 0.0) |
| 9009 | read_only | hedge_roe = float(built_out.get("hedge_roe_pct") or lock_payload.get("hedge_roe_pct") or roe_pct) |
| 9039 | read_only | f"reason={lock_payload.get('reason')}" |
| 9042 | read_only | detail = f"hedge_lock_active hedge_side={hedge_side} close_side={close_side} reason={lock_payload.get('reason')}" |
| 9044 | write_metric | self._publish_skip_event(built_out, "HEDGE_LOCK_BLOCK", detail) |
| 9047 | write_metric | logger.debug(f"[HEDGE_LOCK] publish-time check failed (allowing): {hl_err}") |
| 9051 | write_signal | # Enforce pair-cap limits for all signals at publish time. |
| 9057 | read_only | action_upper = str(built_out.get("action_name") or built_out.get("action") or "").upper() |
| 9061 | read_only | if is_open_increase and not built_out.get("_orch_checked"): |
| 9076 | read_only | sym_u = str(built_out.get("symbol") or "").upper().strip() |
| 9079 | read_only | acct_caps = PER_ACCOUNT_PAIR_CAPS.get(str(account_id).lower(), {}) |
| 9080 | read_only | base_cap = float(acct_caps.get("max_margin_usd") or STACK_OPEN_MAX_MARGIN_USD) |
| 9081 | read_only | pct_cap = float(acct_caps.get("max_equity_pct") or STACK_OPEN_MAX_EQUITY_PCT) |
| 9088 | read_only | eq_raw = self._signal_redis.get(f"portfolio:equity:{account_id}") |
| 9092 | read_only | wallet = float(eq_data.get("wallet_balance_usd") or eq_data.get("wallet_balance") or eq_data.get("balance") or 0) |
| 9093 | read_only | used_margin = float(eq_data.get("used_margin_usd") or eq_data.get("initial_margin_usd") or 0.0) |
| 9107 | read_only | eq_basis = float(eq_data.get("equity_usd") or eq_data.get("margin_balance_usd") or wallet or 0.0) |
| 9119 | write_metric | sym_is_tier3 = bool(sym_u and sym_u in set(TIER3_SYMBOLS or [])) |
| 9125 | read_only | action_u2 = str(built_out.get("action_name") or built_out.get("action") or "").upper() |
| 9130 | read_only | hnc = int(built_out.get("hedge_necessity_class") or 0) |
| 9134 | read_only | pds_val = float(built_out.get("pds") or built_out.get("protection_demand_score") or 0.0) |
| 9160 | read_only | raw_pos = self._signal_redis.hget(pos_key, side_key) |
| 9164 | read_only | leg_margin = abs(float(pos_data.get("margin_used") or pos_data.get("initialMargin") or 0)) |
| 9175 | write_metric | if is_hedge and bool(MANUAL_HEDGE_PAIR_CAP_OVERRIDE_ENABLED) and sym_u not in set(MANUAL_HEDGE_PAIR_CAP_EXCLUDE_SYMBOLS or []): |
| 9178 | read_only | if float(leg_margins.get(leg_side, 0.0)) <= 0.0: |
| 9181 | read_only | raw_origin = self._signal_redis.get(origin_key) if self._signal_redis else None |
| 9186 | read_only | origin_val = json.loads(raw_origin).get("origin") if isinstance(raw_origin, str) else None |
| 9189 | read_only | if str(origin_val or "").lower() == "manual" and float(leg_margins.get(leg_side, 0.0)) > float(base_cap): |
| 9199 | read_only | margin_usd = float(built_out.get("margin_usd") or 0.0) |
| 9208 | read_only | cat0 = str(built_out.get("action_category") or _pc_get_cat(str(action_upper or ""))).upper() |
| 9209 | read_only | is_hedge0 = bool(built_out.get("hedge_intent")) or str(action_upper).startswith(("OPEN_HEDGE_", "ADD_HEDGE_")) |
| 9219 | write_metric | self._publish_skip_event(built_out, "PAIR_CAP_BLOCK", detail) |
| 9229 | read_only | notional0 = float(built_out.get("notional_usd") or 0.0) |
| 9233 | read_only | lev0 = float(built_out.get("leverage") or built_out.get("recommended_leverage") or 0.0) |
| 9242 | read_only | cfg = (SYMBOL_LEVERAGE_CONFIG or {}).get(sym_u, (SYMBOL_LEVERAGE_CONFIG or {}).get("default", {})) or {} |
| 9243 | read_only | sym_max = float(cfg.get("max_leverage", MAX_LEVERAGE) or MAX_LEVERAGE) |
| 9244 | read_only | sym_min = float(cfg.get("min_leverage", 1.0) or 1.0) |
| 9271 | read_only | if built_out.get("notional_usd"): |
| 9281 | write_signal | from utils.signal_publish import publish_trading_signal |
| 9283 | write_signal | stream_id = publish_trading_signal( |
| 9284 | read_only | self._signal_redis, |
| 9287 | read_only | maxlen=maxlen, |
| 9293 | write_metric | # Everything was blocked/skipped at publish-time (e.g., hedge lock on all accounts) |
| 9294 | write_metric | self._publish_skip_event(built, "PUBLISH_SUPPRESSED", "no streams published (all blocked)") |
| 9297 | write_signal | logger.info(f"PUBLISH_OK / {symbol} / {tf} / {action} / streams={len(target_streams)} / ids={stream_ids[0] if len(stream_ids) == 1 else 'multi'}") |
| 9300 | write_metric | # PUBLISH PROOF EMISSION (Jan 24, 2026): |
| 9301 | write_signal | # Emit structured proof for ALL published signals (including asjad). |
| 9313 | read_only | proof_account = str(built.get("account_id") or built.get("account") or "primary").strip().lower() |
| 9320 | read_only | "winner_source": str(built.get("source") or "trainer"), |
| 9321 | read_only | "winner_category": str(built.get("action_category") or "UNKNOWN").upper(), |
| 9322 | read_only | "winner_conf": float(built.get("confidence") or built.get("model_confidence") or 0.0), |
| 9323 | read_only | "margin_usd": float(built.get("margin_usd") or 0.0), |
| 9324 | read_only | "notional_usd": float(built.get("notional_usd") or notional_usd or 0.0), |
| 9325 | read_only | "leverage": int(built.get("leverage") or built.get("recommended_leverage") or 1), |
| 9326 | read_only | "hedge_intent": bool(built.get("hedge_intent")), |
| 9327 | read_only | "profit_intent": bool(built.get("profit_intent")), |
| 9328 | read_only | "no_loss_compliant": bool(built.get("no_loss_compliant")), |
| 9329 | read_only | "resized": bool(built.get("_orch_resized") or built.get("_hedge_headroom_scaled")), |
| 9331 | write_metric | "reason": str(built.get("_orch_resize_reason") or built.get("_hedge_headroom_reason") or "PUBLISHED_OK"), |
| 9332 | write_signal | "event": "SIGNAL_PUBLISHED_PROOF", |
| 9335 | write_signal | self._signal_redis.xadd( |
| 9338 | read_only | maxlen=5000, |
| 9342 | write_metric | logger.debug(f"[PUBLISH_PROOF] Non-critical error: {proof_err}") |
| 9344 | write_metric | # NEXT-CYCLE VALIDATION: Clear staged marker only after successful publish |
| 9347 | write_signal | self._signal_redis.delete(pending_validation_key_to_clear) |
| 9360 | read_only | state_manager = get_signal_state_manager(self._signal_redis) |
| 9383 | read_only | price=float(built.get('trigger_price') or built.get('entry_price') or built.get('price') or 0), |
| 9403 | read_only | price = built.get("trigger_price", 0) or built.get("entry_price", 0) or 0 |
| 9428 | read_only | "confidence": float(built.get("confidence") or built.get("model_confidence") or 0), |
| 9429 | read_only | "price_target": float(built.get("price_target") or 0), |
| 9430 | read_only | "price_target_pct": float(built.get("price_target_pct") or 0), |
| 9431 | read_only | "entry_price": float(built.get("trigger_price") or built.get("entry_price") or built.get("price") or 0), |
| 9432 | read_only | "timeframe": str(built.get("timeframe") or tf or "multi"), |
| 9437 | read_only | self._signal_redis.setex(cache_key, 3600, json.dumps(pred_cache))  # 1h TTL |
| 9443 | write_signal | logger.error(f"PUBLISH_BLOCK / {symbol} / {tf} / {action} / reason={pub_err}") |
| 9444 | write_metric | # CRITICAL: Emit skip event for ALL publish failures |
| 9445 | write_checkpoint_metadata | self._publish_skip_event(payload, "PUBLISH_ERROR", str(pub_err)[:200]) |
| 9460 | write_signal | P0-1 Audit Fix: Emit structured decision log for every published signal. |
| 9464 | read_only | symbol = payload.get("symbol", "?") |
| 9465 | read_only | tf = payload.get("timeframe", "?") |
| 9466 | read_only | action = str(payload.get("action_name") or payload.get("action") or "?")[:20] |
| 9467 | read_only | conf = float(payload.get("confidence", 0)) |
| 9471 | read_only | equity = float(payload.get("equity_snapshot", 0) or |
| 9486 | read_only | pos = real_positions.get(symbol) |
| 9488 | read_only | # Fallback to trader-synced positions from Redis |
| 9493 | read_only | redis_pos = get_pos_fn(symbol) |
| 9494 | read_only | if redis_pos and redis_pos.get('has_position'): |
| 9495 | read_only | pos = redis_pos |
| 9499 | read_only | equity = float(margin_metrics.get('total_wallet_balance', 0) or |
| 9500 | read_only | margin_metrics.get('total_margin_balance', 0) or 1000) |
| 9505 | read_only | pos_side = pos.get("side", "FLAT") |
| 9506 | read_only | pos_qty = abs(float(pos.get("size", 0) or pos.get("positionAmt", 0) or 0)) |
| 9507 | read_only | entry_ts = pos.get("entry_time", pos.get("updateTime", pos.get("timestamp", 0))) |
| 9515 | read_only | upnl_pct = float(pos.get("unrealized_pnl_pct", 0) or pos.get("pnl_pct", 0) or 0) |
| 9516 | read_only | rpnl_today = float(pos.get("realized_pnl_today", 0) or 0) |
| 9522 | read_only | margin_util = float(margin_metrics.get("margin_utilization", 0) or 0) |
| 9531 | read_only | if not timing.get("t_infer"): |
| 9545 | write_checkpoint_metadata | def _publish_skip_event(self, payload: dict, reason_code: str, reason_detail: str): |
| 9546 | write_signal | """Publish structured skip event to signals:execution:skips for observability.""" |
| 9551 | read_only | _raw_action = payload.get("action_name") or payload.get("action") or "" |
| 9555 | read_only | payload["action"] = payload.get("action") or _norm_action |
| 9556 | read_only | if not payload.get("action_category") and _norm_action: |
| 9558 | read_only | if payload.get("hedge_intent") is None: |
| 9559 | read_only | au = str(_norm_action or payload.get("action_name") or payload.get("action") or "").upper() |
| 9560 | read_only | payload["hedge_intent"] = bool(payload.get("action_category") == "HEDGE") or ("HEDGE" in au) |
| 9566 | read_only | acct_raw = payload.get("account_id") or payload.get("_routed_account_id") or payload.get("account") |
| 9577 | read_only | symbol = payload.get("symbol") |
| 9578 | read_only | action_u = str(payload.get("action") or payload.get("action_name") or "UNKNOWN").upper() |
| 9579 | read_only | if acct is None and symbol and getattr(self, "_signal_redis", None): |
| 9605 | read_only | raw = self._signal_redis.hget(f"portfolio:positions:{aid}", f"{symbol}:{required_existing_side}") |
| 9616 | read_only | sz = abs(float((pos or {}).get("size", 0) or 0.0)) |
| 9626 | read_only | payload.get("equity_snapshot") |
| 9627 | read_only | or payload.get("portfolio_balance") |
| 9628 | read_only | or payload.get("equity_usd") |
| 9629 | read_only | or payload.get("total_margin_balance") |
| 9632 | read_only | if (not equity_seen) and acct and getattr(self, "_signal_redis", None): |
| 9634 | read_only | st = self._signal_redis.hgetall(f"portfolio:state:{acct}") or {} |
| 9638 | read_only | v = st.get(k) |
| 9648 | read_only | "timeframe": payload.get("timeframe"), |
| 9650 | read_only | "action_type": self._classify_action_type(payload.get("action") or payload.get("action_name")), |
| 9651 | read_only | "action_category": payload.get("action_category"), |
| 9652 | read_only | "hedge_intent": bool(payload.get("hedge_intent")), |
| 9653 | read_only | "source": payload.get("source") or payload.get("decision_source"), |
| 9654 | read_only | "confidence": payload.get("confidence", 0.0), |
| 9657 | read_only | "stream_id": payload.get("_stream_id"), |
| 9658 | read_only | "contract_version": payload.get("contract_version", "margin_v1"), |
| 9664 | write_signal | self._signal_redis.xadd( |
| 9667 | read_only | maxlen=5000, |
| 9671 | write_metric | logger.debug(f"[PUBLISH_SKIP] failed: {skip_err}") |
| 9702 | read_only | action_name = action_mapping.get(action_value, action_value) |
| 9705 | read_only | side = str(position.get('side', '') or 'FLAT').upper() |
| 9706 | read_only | entry_price = float(position.get('entryPrice', 0) or position.get('entry_price', 0) or 0) |
| 9707 | read_only | mark_price = float(position.get('markPrice', 0) or position.get('mark_price', 0) or entry_price) |
| 9773 | write_metric | # Cannot publish without sizing |
| 9857 | read_only | redis_client = getattr(self, 'redis', None) |
| 9859 | read_only | redis_client = None |
| 9860 | read_only | if redis_client: |
| 9867 | read_only | redis_client.setex('rl:blend_telemetry', 60, json.dumps(telemetry)) |
| 9954 | write_signal | # NOTE: All signal publishing happens in trainer paths only |
| 9955 | write_signal | # (_publish_decisions_batch, _make_ppo_prediction) - not in policy.forward |
| 9982 | read_only | # SubprocVecEnv workers can hang on Redis I/O, causing entire rollout to block |
| 10038 | read_only | Removes unpicklable objects (Redis, live_config, promotion_controller). |
| 10044 | read_only | state['_signal_redis'] = None |
| 10056 | read_only | Redis, live_config, and promotion_controller are recreated lazily. |
| 10068 | read_only | # _signal_redis, _live_config, _promotion_controller will be created |
| 10076 | read_only | pair. The env reads ONLY that hash from Redis and builds observations matching |
| 10168 | write_metric | self.reset() |
| 10286 | read_only | pnl_change = float(info.get('pnl_change', 0.0)) if info else 0.0 |
| 10287 | read_only | trade_executed_flag = bool(info.get('trade_executed', False)) if info else False |
| 10288 | read_only | realized_pnl_usd = float(info.get('realized_pnl_usd', 0.0)) if info else 0.0 |
| 10289 | read_only | self.ep_raw_reward[i] += float(info.get('raw_reward', 0.0)) if info else 0.0 |
| 10290 | read_only | self.ep_risk_reward[i] += float(info.get('risk_adjusted_reward', reward_scalar)) if info else 0.0 |
| 10308 | write_metric | obs, _ = env.reset() |
| 10365 | write_metric | # Publish lightweight episode summary for external monitors/debug streams |
| 10367 | read_only | if hasattr(self, '_signal_redis') and self._signal_redis: |
| 10368 | write_signal | self._signal_redis.xadd( |
| 10382 | read_only | maxlen=2000, |
| 10418 | write_metric | def reset(self): |
| 10425 | write_metric | obs, _ = env.reset() |
| 10539 | read_only | and builds observations by reading unified_features:{symbol}:{tf} from Redis, |
| 10589 | read_only | self._feature_key_order = None  # Built lazily on first Redis read |
| 10601 | read_only | # Redis: Store CONFIG (picklable), create client LAZILY per-process |
| 10603 | read_only | self.redis = None  # Created lazily in _ensure_redis() |
| 10605 | read_only | from utils.redis_client import get_redis_config |
| 10606 | read_only | self._redis_cfg = get_redis_config()  # Picklable config dict |
| 10608 | read_only | self._redis_cfg = None |
| 10618 | read_only | Excludes unpicklable objects (Redis client, CUDA tensors). |
| 10622 | read_only | # Remove unpicklable Redis client (will be recreated from _redis_cfg) |
| 10623 | read_only | state['redis'] = None |
| 10639 | read_only | Redis and CUDA will be initialized lazily on first use. |
| 10642 | read_only | # Redis will be created lazily in _ensure_redis() from _redis_cfg |
| 10645 | read_only | def _ensure_redis(self): |
| 10646 | read_only | """Ensure Redis connection is available (multiprocessing-safe) |
| 10648 | read_only | Creates Redis client LAZILY per-process from stored config. |
| 10650 | read_only | if getattr(self, 'redis', None) is None: |
| 10652 | read_only | if getattr(self, '_redis_cfg', None): |
| 10653 | read_only | from utils.redis_client import create_redis_from_config |
| 10654 | read_only | self.redis = create_redis_from_config(self._redis_cfg) |
| 10655 | read_only | logger.debug(f"🔄 Redis created from config in PID {os.getpid()}") |
| 10657 | read_only | self.redis = get_redis() |
| 10659 | read_only | logger.warning(f"⚠️ Redis connection failed: {e}") |
| 10660 | read_only | self.redis = None |
| 10661 | read_only | return self.redis |
| 10729 | read_only | if not hasattr(self, 'redis') or self.redis is None: |
| 10735 | read_only | market_data = self.redis.get(market_key) |
| 10738 | read_only | close_price = float(data.get('close', 0.0)) |
| 10747 | read_only | binance_data = self.redis.get(binance_key) |
| 10750 | read_only | price = float(data.get('price', 0.0)) |
| 10760 | read_only | def _get_price_from_redis(self, symbol: str) -> float: |
| 10782 | read_only | # Get normalization stats from Redis (rolling window stats) |
| 10784 | read_only | norm_stats = self.redis.hgetall(norm_key) |
| 10796 | read_only | mean = float(norm_stats.get(f"{stat_key}_mean", 0.0)) |
| 10797 | read_only | std = float(norm_stats.get(f"{stat_key}_std", 1.0)) |
| 10809 | read_only | mean = float(norm_stats.get(f"{stat_key}_mean", 0.0)) |
| 10810 | read_only | std = float(norm_stats.get(f"{stat_key}_std", 1.0)) |
| 10845 | read_only | norm_stats = self.redis.hgetall(norm_key) or {} |
| 10853 | read_only | old_mean = float(norm_stats.get(f"{stat_key}_mean", value)) |
| 10854 | read_only | old_var = float(norm_stats.get(f"{stat_key}_var", 1.0)) |
| 10871 | read_only | old_mean = float(norm_stats.get(f"{stat_key}_mean", value)) |
| 10872 | read_only | old_var = float(norm_stats.get(f"{stat_key}_var", 1.0)) |
| 10881 | read_only | # Save stats back to Redis with 1 hour expiry |
| 10882 | write_metric | self.redis.hset(norm_key, mapping=norm_stats) |
| 10883 | read_only | self.redis.expire(norm_key, 3600) |
| 10899 | read_only | 1. Read unified_features:{assigned_symbol}:{assigned_tf} from Redis |
| 10914 | read_only | # Ensure Redis is available (lazy init for multiprocessing safety) |
| 10915 | read_only | self._ensure_redis() |
| 10920 | read_only | # Use cached features if available (cache for 1 second to reduce Redis load) |
| 10927 | read_only | redis_key = f"unified_features:{self.assigned_symbol}:{self.assigned_tf}" |
| 10929 | read_only | # Safety check for Redis connection |
| 10930 | read_only | if self.redis is None: |
| 10931 | read_only | logger.warning(f"Redis not available for {redis_key}, using default features") |
| 10935 | read_only | raw_hash = self.redis.hgetall(redis_key) |
| 10938 | read_only | logger.debug(f"No features in {redis_key}, using defaults") |
| 10941 | read_only | # Decode bytes if needed (Redis may return bytes or strings) |
| 10951 | write_metric | keys_set = set() |
| 10975 | read_only | vv = fdict.get(kk) |
| 11077 | read_only | data = self.redis.hgetall(key) |
| 11091 | read_only | price = float(data.get("close") or data.get("price") or data.get("last_price") or 0.0) |
| 11092 | read_only | ll = float(data.get("liquidation_long_level") or 0.0) |
| 11093 | read_only | sl = float(data.get("liquidation_short_level") or 0.0) |
| 11094 | read_only | lstr = float(data.get("liquidation_long_strength") or 0.0) |
| 11095 | read_only | sstr = float(data.get("liquidation_short_strength") or 0.0) |
| 11123 | read_only | last = self._liq_tf_last_log.get(symbol, 0) |
| 11131 | read_only | f"{tf} ll={m.get('long_level',0):.2f} sl={m.get('short_level',0):.2f} " |
| 11132 | read_only | f"ls={m.get('long_strength',0):.2f} ss={m.get('short_strength',0):.2f}" |
| 11157 | read_only | data = self.redis.hgetall(key) |
| 11160 | read_only | ts = int(data.get("liquidation_updated_ts", 0) or 0) |
| 11165 | read_only | price = float(data.get("close") or data.get("price") or data.get("last_price") or 0.0) |
| 11166 | read_only | ll = float(data.get("liquidation_long_level") or 0.0) |
| 11167 | read_only | sl = float(data.get("liquidation_short_level") or 0.0) |
| 11168 | read_only | lstr = float(data.get("liquidation_long_strength") or 0.0) |
| 11169 | read_only | sstr = float(data.get("liquidation_short_strength") or 0.0) |
| 11198 | read_only | weight = tf_weights.get(tf, 0.2) |
| 11318 | read_only | Load global market-wide features from Redis |
| 11344 | read_only | data_str = self.redis.get(key) |
| 11350 | read_only | value = data.get('count', data.get('score', data.get('avg_score', 0.0))) |
| 11379 | read_only | data_str = self.redis.get(key) |
| 11383 | read_only | value = data.get('value', data.get('index', data.get('ratio', 0.0))) |
| 11444 | read_only | file_path = file_path_lower if file_path_lower.exists() else file_path_upper |
| 11446 | read_only | if not file_path.exists(): |
| 11468 | read_only | float(candle.get('open', 0)), |
| 11469 | read_only | float(candle.get('high', 0)), |
| 11470 | read_only | float(candle.get('low', 0)), |
| 11471 | read_only | float(candle.get('close', 0)), |
| 11472 | read_only | float(candle.get('volume', 0)) |
| 11577 | read_only | # Ensure CUDA and Redis are initialized |
| 11579 | read_only | self._ensure_redis() |
| 11583 | read_only | size_suggest = float(hedge_action_result.get('size_suggest', 0.05)) |
| 11584 | read_only | lev_suggest = float(hedge_action_result.get('lev_suggest', 5.0)) |
| 11585 | read_only | confidence = float(hedge_action_result.get('confidence', 0.5)) |
| 11588 | read_only | action_value = int(hedge_action_result.get('action_id', action)) |
| 11667 | read_only | # Redis and provides a directional bias. This shapes the reward to |
| 11689 | read_only | _ta_rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 11700 | read_only | _ta_dir = _ta_res.get("direction", 0) |
| 11701 | read_only | _ta_str = _ta_res.get("strength", 0.0) |
| 11709 | read_only | f"action={action} redis={'OK' if _ta_rc else 'NONE'}", |
| 11878 | read_only | action_name = ACTION_ID_TO_NAME.get(action, "HOLD") |
| 11892 | read_only | if LATEST_POLICY_PARAMS.get('size') is not None: |
| 11894 | read_only | if LATEST_POLICY_PARAMS.get('leverage') is not None: |
| 11896 | read_only | if LATEST_POLICY_PARAMS.get('action_probs') is not None: |
| 11956 | read_only | """Get current price for ASSIGNED SYMBOL from Redis market data. |
| 11978 | read_only | if self._price_warning_count.get(self.assigned_symbol, 0) < 5: |
| 11980 | read_only | self._price_warning_count[self.assigned_symbol] = self._price_warning_count.get(self.assigned_symbol, 0) + 1 |
| 12033 | write_metric | self._invalid_price_logged = set() |
| 12070 | read_only | _prev_dir = int(_meta.get("dir", 0) or 0) |
| 12071 | read_only | _prev_ts = float(_meta.get("ts", 0.0) or 0.0) |
| 12072 | read_only | _prev_px = float(_meta.get("price", 0.0) or 0.0) |
| 12124 | read_only | lev_cfg = self.symbol_leverage_ranges.get(symbol, self.symbol_leverage_ranges.get('default', {'min_leverage': 0.5, 'max_leverage': 10.0})) |
| 12125 | read_only | lev_suggest = max(float(lev_cfg.get('min_leverage', 0.5)), min(float(lev_suggest), float(lev_cfg.get('max_leverage', 10.0)))) |
| 12147 | read_only | dyn_target = float(sizing.get("target_exposure_pct", target_fraction)) |
| 12558 | read_only | # Redis timeout settings for SubprocVecEnv stability |
| 12559 | read_only | self.redis_timeout = 2.0  # Reduced timeout for faster failure detection |
| 12560 | read_only | self.redis_retry_attempts = 2  # Quick retry for transient failures |
| 12636 | read_only | self.redis = get_redis() |
| 12638 | read_only | sys.stderr.write("[TRAINER-INIT] 1. Config and Redis initialized\n") |
| 12650 | read_only | # This sets Redis-backed HEDGE_BUILD state even before the first prediction loop starts. |
| 12670 | read_only | self._warm_start = get_warm_start_manager(redis_client=self.redis) |
| 12737 | read_only | logger.info("✅ Dynamic portfolio mode confirmed - will sync from Redis/[REDACTED]") |
| 12753 | read_only | redis_client=self.redis, |
| 12768 | write_metric | # Pass Redis so it can read position data published by traders |
| 12769 | read_only | self.portfolio_tracker = MultiAccountPortfolioTracker(redis_client=self.redis) |
| 12778 | read_only | self.increase_validator = IncreaseSignalValidator(redis_client=self.redis) |
| 12940 | read_only | self.confidence_history = defaultdict(lambda: deque(maxlen=self.config.adaptive_threshold_window)) |
| 12943 | read_only | self._temporal_buffers = defaultdict(lambda: defaultdict(lambda: deque(maxlen=128)))  # Observations (1053-dim) |
| 12944 | read_only | self._regime_buffers = defaultdict(lambda: defaultdict(lambda: deque(maxlen=5)))  # Regime features (8-dim) |
| 12952 | write_signal | # Initialize signal publisher |
| 12953 | read_only | self._signal_redis = None |
| 12985 | write_metric | 'published_count': 0, |
| 12989 | write_metric | logger.info("📊 Phase 0 baseline counters initialized: buffered/published/suppressed tracking") |
| 12995 | write_metric | self._canary_zero_publish_cycles = 0 |
| 13003 | read_only | self._exec_event_maxlen = int(getattr(self.main_config, "STREAM_MAXLEN_EXEC_EVENTS", 100000)) |
| 13005 | read_only | self._exec_event_maxlen = 100000 |
| 13035 | write_metric | # Structure: f"{symbol}:{category}" -> last_published_ts_ms |
| 13036 | write_metric | self._last_published_ts = {} |
| 13037 | write_metric | self._last_published_lock = threading.Lock() |
| 13044 | read_only | # Redis-backed rolling counters for rate limiting (3600s TTL) |
| 13046 | write_risk_state | # Cooldowns: cooldown:open_risk:{symbol} (setex when OPEN_RISK published) |
| 13158 | read_only | self.liquidation_intelligence = LiquidationIntelligenceService(self.redis, self.binance_client) |
| 13206 | write_metric | # Publish status to Redis for dashboard |
| 13208 | read_only | from utils.redis_client import get_redis_client |
| 13209 | read_only | rc = get_redis_client() |
| 13210 | write_metric | rc.set('trainer:critical_fixes:initialized', 'true') |
| 13211 | write_metric | rc.hset('trainer:critical_fixes:stats', mapping={ |
| 13217 | write_metric | print("✅ [ADDITIONAL_FIXES] Dashboard status published to Redis", flush=True) |
| 13218 | read_only | except Exception as redis_err: |
| 13219 | write_metric | print(f"⚠️ [ADDITIONAL_FIXES] Redis publish failed (non-critical): {redis_err}", flush=True) |
| 13245 | write_metric | self.exec_event_publisher = None |
| 13257 | write_metric | self.exec_event_publisher |
| 13259 | read_only | redis_client=self.redis, |
| 13265 | write_metric | # Publish status to Redis |
| 13267 | read_only | rc = self.redis or get_redis() |
| 13268 | write_metric | rc.hset('trainer:liq_prevention:status', mapping={ |
| 13275 | read_only | except Exception as redis_err: |
| 13276 | write_metric | logger.debug(f"[LIQ-PREVENTION] Redis status publish failed: {redis_err}") |
| 13292 | read_only | self.adaptive_hedge_builder = get_adaptive_hedge_builder(redis_client=self.redis) |
| 13320 | read_only | self._confidence_logger = ConfidenceLogger(self.redis, max_records=10000) |
| 13332 | read_only | initialize_feedback_system(self.redis) |
| 13341 | read_only | self._calibration_manager = CalibratedConfidenceManager(self.redis) |
| 13356 | read_only | # Phase 6: ThresholdRamper — writes adaptive threshold to Redis |
| 13360 | read_only | self._threshold_ramper = ThresholdRamper(self.redis) |
| 13385 | read_only | cal = sym_data.get('calibration', {}) |
| 13386 | read_only | samples = sym_data.get('samples', 0) |
| 13421 | read_only | then writes updated threshold to Redis ``rl:config:threshold``. |
| 13432 | read_only | status = result.get('status', 'unknown') |
| 13436 | read_only | result.get('old_threshold', 0), result.get('new_threshold', 0), |
| 13437 | read_only | result.get('reason', ''), |
| 13461 | read_only | if _replay_reset and _persist_path and os.path.exists(_persist_path): |
| 13561 | read_only | redis_client=self.redis, |
| 13581 | read_only | redis_client=self.redis, |
| 13615 | read_only | if getattr(self, "redis", None): |
| 13617 | read_only | if self.redis.get(key): |
| 13619 | read_only | self.redis.setex(key, 15, "1") |
| 13675 | write_heartbeat | # Heartbeat Publisher (Proof of liveness for monitoring) |
| 13679 | write_heartbeat | """Start periodic heartbeat publisher for health monitoring. |
| 13681 | write_heartbeat | Publishes to Redis key `heartbeat:trainer` every HEARTBEAT_INTERVAL_SECONDS. |
| 13684 | read_only | Runs in background thread, fails gracefully if Redis unavailable. |
| 13691 | write_heartbeat | """Background worker that publishes periodic heartbeat""" |
| 13705 | write_metric | # Publish to Redis with TTL |
| 13706 | read_only | self.redis.setex( |
| 13714 | write_heartbeat | logger.info(f"[HEARTBEAT_PUBLISHED] interval={HEARTBEAT_INTERVAL_SECONDS}s ttl={HEARTBEAT_TTL_SECONDS}s") |
| 13855 | read_only | fast_move_up = features.get('fast_move_up', False) |
| 13856 | read_only | range_1m = abs(features.get('high_1m', 0) - features.get('low_1m', 0)) |
| 13857 | read_only | range_5m = abs(features.get('high_5m', 0) - features.get('low_5m', 0)) |
| 13860 | read_only | spoof_score = features.get('spoof_score', 0) |
| 13861 | read_only | spread_widening = features.get('spread_change', 0) > 0.3 |
| 13864 | read_only | vwap_dist = abs(features.get('distance_from_vwap', 0)) |
| 13865 | read_only | ema_dist = abs(features.get('distance_from_ema', 0)) |
| 13948 | write_signal | Returns list of hedge signals to publish. |
| 13964 | read_only | redis = getattr(self, 'redis', None) or getattr(self, '_signal_redis', None) |
| 13965 | read_only | if not redis: |
| 13980 | read_only | pos_data = redis.hgetall(pos_key) |
| 13993 | read_only | side = str(pos.get('side', '')).upper() |
| 13996 | read_only | if not pos.get('has_position', False): |
| 13998 | read_only | if abs(float(pos.get('size', 0) or 0)) <= 0: |
| 14013 | read_only | side = str(pos.get('side', '')).upper() |
| 14014 | read_only | account_id = pos.get('account_id', 'primary') |
| 14018 | read_only | last_frh = self._frh_cooldown.get(cd_key, 0) |
| 14024 | read_only | entry_ts = float(pos.get('open_time', 0) or pos.get('entry_time', 0) or pos.get('created_ts', 0) or 0) |
| 14037 | read_only | opp_raw = redis.hget(f'portfolio:positions:{account_id}', opp_field) |
| 14041 | read_only | if opp_pos.get('has_position', False) and abs(float(opp_pos.get('size', 0) or 0)) > 0: |
| 14050 | read_only | opp_notional = abs(float(opp_pos.get('notional', 0) or 0)) |
| 14051 | read_only | main_notional = abs(float(pos.get('notional', 0) or 0)) |
| 14053 | read_only | size_qty = abs(float(pos.get('size', 0) or 0)) |
| 14054 | read_only | mark_px = float(pos.get('mark_price', 0) or pos.get('current_price', 0) or 0) |
| 14070 | read_only | ob_raw = redis.get(f'orderbook:top:{symbol}') |
| 14074 | read_only | ob_imb = float(ob.get('imbalance', 0) or 0) |
| 14090 | read_only | f1m = redis.hgetall(f'unified_features:{symbol}:1m') |
| 14095 | read_only | rsi = float(f1m.get('ind_ta_RSI_14_1m', 50) or 50) |
| 14096 | read_only | # Use actual Redis key names for MACD (try multiple patterns) |
| 14098 | read_only | f1m.get('ind_ta_MACD_hist_fastperiod12_slowperiod26_signalperiod9_1m', 0) or |
| 14099 | read_only | f1m.get('ind_ta_MACD_12_26_9_1m', 0) or 0 |
| 14102 | read_only | f1m.get('ind_ta_MACD_signal_fastperiod12_slowperiod26_signalperiod9_1m', 0) or |
| 14103 | read_only | f1m.get('ind_ta_MACDs_12_26_9_1m', 0) or 0 |
| 14135 | read_only | msnap = redis.hgetall(f'msnap:coinapi_wsds:{symbol}') |
| 14138 | read_only | fast_move = float(msnap.get('fast_move_score', 0) or 0) |
| 14139 | read_only | spoof = float(msnap.get('spoof_score', 0) or 0) |
| 14140 | read_only | p_false = float(msnap.get('p_false_move', 0) or 0) |
| 14141 | read_only | micro_imb = float(msnap.get('imbalance_5', 0) or 0) |
| 14167 | read_only | entry_px = float(pos.get('entry_price', 0) or pos.get('avg_entry', 0) or 0) |
| 14168 | read_only | mark_px = float(pos.get('mark_price', 0) or pos.get('current_price', 0) or 0) |
| 14171 | read_only | leverage = float(pos.get('leverage', 1) or 1) |
| 14207 | read_only | size_qty = abs(float(pos.get('size', 0) or 0)) |
| 14208 | read_only | mark_px = float(pos.get('mark_price', 0) or pos.get('current_price', 0) or 0) |
| 14210 | read_only | px_raw = redis.get(f'price:{symbol}') |
| 14215 | read_only | mark_px = float(px_data.get('price', 0) or px_data) if isinstance(px_data, dict) else float(px_data) |
| 14219 | read_only | leverage = float(pos.get('leverage', 1) or 1) |
| 14232 | read_only | entry_px = float(pos.get('entry_price', 0) or pos.get('entryPrice', 0) or 0) |
| 14267 | read_only | opp_raw_cap = redis.hget(f'portfolio:positions:{account_id}', opp_field_cap) |
| 14272 | read_only | existing_hedge_notional = abs(float(opp_pos_cap.get('notional', 0) or 0)) |
| 14367 | write_signal | Returns list of hedge signals to publish. |
| 14386 | read_only | redis = getattr(self, "redis", None) or getattr(self, "_signal_redis", None) |
| 14387 | read_only | if not redis: |
| 14388 | read_only | logger.info("[HEDGE_BUILDER_V2] No Redis connection - skipping") |
| 14394 | read_only | edge_gate = get_adaptive_edge_gate(redis_client=redis) |
| 14412 | read_only | size_qty = abs(float(p.get("size", 0) or 0)) |
| 14413 | read_only | px = float(p.get("mark_price") or p.get("current_price") or p.get("entry_price") or 0) |
| 14419 | read_only | return abs(float(p.get("notional", 0) or p.get("size_usd", 0) or 0)) |
| 14427 | read_only | pos_data = redis.hgetall(pos_key) |
| 14440 | read_only | side = str(pos.get("side", "")).upper() |
| 14443 | read_only | if not pos.get("has_position", False): |
| 14445 | read_only | if abs(float(pos.get("size", 0) or 0)) <= 0: |
| 14459 | read_only | long_pos = by_side.get("LONG") |
| 14460 | read_only | short_pos = by_side.get("SHORT") |
| 14483 | read_only | entry_price = float(primary_pos.get("entry_price", 0) or primary_pos.get("avg_entry", 0) or 0) |
| 14547 | read_only | hedge_pos = by_side.get(hedge_side) |
| 14549 | read_only | hedge_upnl = float((hedge_pos or {}).get("unrealized_pnl", 0.0) or 0.0) |
| 14624 | read_only | if redis.get(pending_key): |
| 14638 | read_only | _ep2 = float(primary_pos.get('entry_price', 0) or primary_pos.get('entryPrice', 0) or 0) |
| 14639 | read_only | _mp2 = float(primary_pos.get('mark_price', 0) or primary_pos.get('current_price', 0) or 0) |
| 14640 | read_only | _lv2 = float(primary_pos.get('leverage', 1) or 1) |
| 14660 | read_only | sym_min = float((BINANCE_FUTURES_MIN_NOTIONAL_USD_BY_SYMBOL or {}).get(symbol, MIN_NOTIONAL_USD) or MIN_NOTIONAL_USD) |
| 14667 | write_signal | # Contract sizing fields required by canonical publisher for entry-type actions. |
| 14672 | read_only | lev = float(primary_pos.get("leverage", 1) or 1) |
| 14706 | read_only | raw_eq = redis.get(f"portfolio:equity:{account_id}") |
| 14711 | read_only | eq_usd = float(eq_data.get("equity_usd", 0.0) or 0.0) |
| 14725 | read_only | if not margin_check.get("can_trade", False): |
| 14728 | read_only | f"reason={margin_check.get('reason')} / util={float(margin_check.get('margin_utilization', 0.0) or 0.0):.1f}%" |
| 14732 | read_only | if bool(margin_check.get("size_reduced")): |
| 14747 | read_only | redis.setex(pending_key, ttl, "1") |
| 14826 | read_only | fee_roe = market_context.get('fee_roe', 0) |
| 14831 | read_only | vol_roe = market_context.get('vol_roe', 0) |
| 14837 | read_only | micro_details = market_context.get('micro_details', {}) |
| 14848 | read_only | adjustments = market_context.get('adjustments', {}) |
| 14852 | read_only | funding_info = market_context.get('funding', 'N/A') |
| 14854 | read_only | funding_adj = adjustments.get('funding', 1.0) |
| 14859 | read_only | oi_info = market_context.get('oi', 'N/A') |
| 14861 | read_only | oi_adj = adjustments.get('oi', 1.0) |
| 14866 | read_only | regime_info = market_context.get('regime', 'UNKNOWN') |
| 14868 | read_only | regime_adj = adjustments.get('regime', 1.0) |
| 14898 | read_only | redis = getattr(self, 'redis', None) or getattr(self, '_signal_redis', None) |
| 14899 | read_only | if not redis: |
| 14900 | read_only | logger.debug("[PROFIT_SCANNER] No Redis connection") |
| 14929 | read_only | size_qty = abs(_float(p.get("size", 0) or 0)) |
| 14930 | read_only | px = _float(p.get("mark_price", 0) or p.get("current_price", 0) or p.get("entry_price", 0) or 0) |
| 14935 | read_only | return abs(_float(p.get("notional", 0) or p.get("size_usd", 0) or 0)) |
| 14948 | read_only | upnl = _float(p.get("unrealized_pnl", None), default=None) |
| 14950 | read_only | p.get("margin_used", None) |
| 14951 | read_only | or p.get("initialMargin", None) |
| 14952 | read_only | or p.get("margin", None), |
| 14961 | read_only | p.get("roe_pct", 0) |
| 14962 | read_only | or p.get("roi_pct", 0) |
| 14963 | read_only | or p.get("pnl_percentage", 0) |
| 14964 | read_only | or p.get("unrealized_pnl_pct", 0) |
| 14965 | read_only | or p.get("pnl_pct", 0) |
| 14970 | read_only | return _float(p.get("entry_price", 0) or p.get("avg_entry", 0) or 0) |
| 14983 | read_only | raw = redis.get(ride_key) |
| 14990 | read_only | if not bool(data.get("suppress_tp")): |
| 14992 | read_only | ride_side = str(data.get("side") or "").upper() |
| 14998 | read_only | squeeze = float(data.get("squeeze_potential", 0) or 0.0) |
| 15002 | read_only | momentum = abs(float(data.get("momentum_score", 0) or 0.0)) |
| 15006 | read_only | fast_move = float(data.get("fast_move_score", 0) or 0.0) |
| 15011 | read_only | return True, str(data.get("reason") or "ride_move"), float(cont_strength), (data or {}) |
| 15022 | read_only | raw = redis.get(ride_key) |
| 15029 | read_only | if not bool(data.get("suppress_tp")): |
| 15031 | read_only | return True, str(data.get("reason") or "ride_move"), (data or {}) |
| 15048 | read_only | uf = redis.hgetall(f"unified_features:{sym_u}:5m") or {} |
| 15056 | read_only | ms = redis.hgetall(f"msnap:coinapi_wsds:{sym_u}") or {} |
| 15060 | read_only | updated_ts = int(float((ms or {}).get("updated_ts_ms", 0) or 0)) |
| 15069 | read_only | liq = redis.hgetall(f"binance_liq:{sym_u}") or {} |
| 15076 | read_only | liq_updated_ts = int(float((uf or {}).get("liquidation_updated_ts", 0) or 0)) |
| 15085 | read_only | if not ((uf or {}).get("liquidation_levels_json") or (uf or {}).get("liquidation_source")): |
| 15096 | read_only | raw_f = redis.get(f"[REDACTED]:funding:{sym_u}") |
| 15097 | read_only | raw_o = redis.get(f"[REDACTED]:oi:{sym_u}") |
| 15117 | read_only | raw = redis.get(f"market:{symbol}:{tf}") |
| 15127 | read_only | ts_ms = int(data.get("timestamp", 0) or data.get("ts_ms", 0) or 0) |
| 15136 | read_only | }.get(tf, 15 * 60 * 1000) |
| 15140 | read_only | high = float(data.get("high", 0) or 0) |
| 15141 | read_only | low = float(data.get("low", 0) or 0) |
| 15142 | read_only | close = float(data.get("close", 0) or 0) |
| 15164 | read_only | raw = redis.get(f"volatility:{symbol}") |
| 15169 | read_only | ci = float(data.get("composite_index", 0) or 0)  # percent |
| 15195 | read_only | pos_keys = redis.keys(pattern) |
| 15199 | read_only | pos_hash = redis.hgetall(pos_key_str) |
| 15212 | read_only | long_raw = pos_hash.get(b"long") or pos_hash.get("long") |
| 15215 | read_only | size = abs(float(pos.get("size", 0) or 0)) |
| 15222 | read_only | short_raw = pos_hash.get(b"short") or pos_hash.get("short") |
| 15225 | read_only | size = abs(float(pos.get("size", 0) or 0)) |
| 15240 | read_only | raw_map = redis.hgetall(canonical_key) or {} |
| 15253 | read_only | if legs_by_key.get(key, {}).get(side_c) is not None: |
| 15256 | read_only | size = abs(float(pos.get("size", 0) or pos.get("positionAmt", 0) or 0)) |
| 15280 | read_only | long_pos = sides.get("LONG") |
| 15281 | read_only | short_pos = sides.get("SHORT") |
| 15293 | read_only | raw_h = redis.get(f"hedge:active:{symbol}:{account_id}") |
| 15298 | read_only | ms = str(hdata.get("main_position_side") or hdata.get("main_side") or "").upper() |
| 15299 | read_only | hs = str(hdata.get("hedge_position_side") or hdata.get("hedge_side") or "").upper() |
| 15317 | read_only | side = str(pos.get("side") or "").upper() |
| 15341 | read_only | lev = _float(pos.get("leverage", 0) or 0, default=0.0) |
| 15344 | read_only | margin_used = _float(pos.get("margin_used", 0) or pos.get("initialMargin", 0) or 0, default=0.0) |
| 15357 | read_only | # Microstructure pressure (0..1). Use cached analyzer (fast; Redis-backed). |
| 15364 | read_only | 'mm_score': float(micro.get("market_maker_score", 0.0) or 0.0), |
| 15365 | read_only | 'snapback': float(micro.get("snapback_score", 0.0) or 0.0), |
| 15366 | read_only | 'fast_persist': float(micro.get("fast_move_persist", 0.0) or 0.0), |
| 15380 | read_only | regime_raw = redis.get(regime_key) |
| 15383 | read_only | regime = str((regime_data or {}).get("regime", "RANGE") or "RANGE").upper() |
| 15390 | read_only | fake_breakout_risk = float((micro or {}).get("fake_breakout_risk", 0.0) or 0.0) |
| 15397 | read_only | fast_persist = float((micro or {}).get("fast_move_persist", micro_details.get("fast_persist", 0.0)) or 0.0) |
| 15427 | read_only | _fm_ret60 = abs(float((micro or {}).get("ret_60s", 0) or 0)) |
| 15428 | read_only | _fm_ret30 = abs(float((micro or {}).get("ret_30s", 0) or 0)) |
| 15429 | read_only | _fm_score = float((micro or {}).get("fast_move_score", 0) or 0) |
| 15439 | read_only | snapback_score = float(micro_details.get('snapback', 0.0) or 0.0) |
| 15446 | read_only | raw_peak = redis.get(peak_key) |
| 15452 | read_only | stored_peak = float(pdata.get("peak_roe", roe_pct) or roe_pct) |
| 15465 | read_only | pred_raw = redis.get(pred_key) |
| 15468 | read_only | pred_direction = str(pred_data.get('direction', '') or pred_data.get('action', '') or '').upper() |
| 15469 | read_only | prediction_confidence = float(pred_data.get('confidence', 0) or pred_data.get('model_confidence', 0) or 0) |
| 15470 | read_only | predicted_target_pct = abs(float(pred_data.get('price_target_pct', 0) or 0)) |
| 15587 | read_only | funding_raw = redis.get(funding_key) |
| 15591 | read_only | funding_rate = float(funding_data.get("funding_rate", 0) or funding_data.get("rate", 0) or 0) |
| 15615 | read_only | oi_raw = redis.get(oi_key) |
| 15619 | read_only | oi_change = float(oi_data.get("oi_change_pct", 0) or oi_data.get("change_pct", 0) or 0) |
| 15691 | read_only | raw_peak = redis.get(peak_key) |
| 15696 | read_only | peak_roe = float(pdata.get("peak_roe", peak_roe) or peak_roe) |
| 15699 | read_only | redis.setex( |
| 15734 | read_only | last_profit_ts = redis.get(symbol_cooldown_key) |
| 15869 | write_metric | # Compute dominant (main) leg PnL in USD (prefer exchange-published unrealized). |
| 15872 | read_only | (main_pos or {}).get("unrealized_pnl", None) |
| 15873 | read_only | or (main_pos or {}).get("pnl", None) |
| 15874 | read_only | or (main_pos or {}).get("pnl_usd", None), |
| 15945 | read_only | exch_min = float((BINANCE_FUTURES_MIN_NOTIONAL_USD_BY_SYMBOL or {}).get(symbol, 0.0) or 0.0) |
| 15975 | read_only | leg_pos.get("unrealized_pnl", None) |
| 15976 | read_only | or leg_pos.get("unrealized_pnl_usd", None) |
| 15977 | read_only | or leg_pos.get("unRealizedProfit", None) |
| 15978 | read_only | or leg_pos.get("pnl_usd", None) |
| 16024 | read_only | ((long_pos if side == "LONG" else short_pos) or {}).get("mark_price", 0) |
| 16025 | read_only | or ((long_pos if side == "LONG" else short_pos) or {}).get("current_price", 0) |
| 16064 | read_only | "base_threshold": float(market_context.get('base_threshold', min_roe)), |
| 16066 | read_only | "funding_adj": float(market_context.get('adjustments', {}).get('funding', 1.0)), |
| 16067 | read_only | "oi_adj": float(market_context.get('adjustments', {}).get('oi', 1.0)), |
| 16068 | read_only | "regime_adj": float(market_context.get('adjustments', {}).get('regime', 1.0)), |
| 16082 | read_only | redis.setex(symbol_cooldown_key, 30, str(current_time)) |
| 16115 | read_only | if redis.get(cooldown_key): |
| 16123 | read_only | (s.get("account_id") == account_id and s.get("symbol") == symbol and "CLOSE" in str(s.get("action_name") or s.get("action") or "")) |
| 16131 | read_only | long_upnl = _float((long_pos or {}).get("unrealized_pnl", 0.0) or 0.0, 0.0) |
| 16132 | read_only | short_upnl = _float((short_pos or {}).get("unrealized_pnl", 0.0) or 0.0, 0.0) |
| 16165 | read_only | redis.setex(f"wma:paired_close_plan:{pair_id}", 180, json.dumps(plan, separators=(",", ":"))) |
| 16171 | read_only | redis.setex(cooldown_key, 300, str(int(time.time()))) |
| 16222 | read_only | redis = getattr(self, 'redis', None) or getattr(self, '_signal_redis', None) |
| 16223 | read_only | if not redis: |
| 16240 | read_only | size_qty = abs(float(p.get("size", 0) or 0)) |
| 16241 | read_only | px = float(p.get("mark_price") or p.get("current_price") or p.get("entry_price") or 0) |
| 16247 | read_only | return abs(float(p.get("notional", 0) or p.get("size_usd", 0) or 0)) |
| 16257 | read_only | pos_keys = redis.keys(pattern) |
| 16260 | read_only | pos_hash = redis.hgetall(pos_key_str) |
| 16266 | read_only | pos_data = pos_hash.get(side_key) |
| 16274 | read_only | if abs(float(pos.get('size', 0) or 0)) <= 0: |
| 16286 | read_only | long_pos = (by_side or {}).get("LONG") |
| 16287 | read_only | short_pos = (by_side or {}).get("SHORT") |
| 16311 | read_only | last_hedge_ts = redis.get(cooldown_key) |
| 16325 | read_only | is_flash = micro.get('is_flash_move', False) |
| 16326 | read_only | flash_pct = micro.get('flash_move_pct', 0.0) |
| 16327 | read_only | flash_direction = micro.get('flash_move_direction') |
| 16328 | read_only | spoof_score = micro.get('spoof_score', 0.0) |
| 16377 | read_only | lev = float((primary_pos or {}).get("leverage", 1) or 1) |
| 16402 | read_only | redis.setex(cooldown_key, FLASH_HEDGE_COOLDOWN_SECONDS, str(current_time)) |
| 16429 | read_only | redis = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 16430 | read_only | if not redis: |
| 16439 | read_only | if redis.exists(cd_key): |
| 16446 | read_only | _raw = redis.hgetall(_pk) |
| 16454 | read_only | side = str(pos_data.get("side", "") or "").upper() |
| 16459 | read_only | roe = float(pos_data.get("roe_pct", 0) or pos_data.get("unrealized_pnl_pct", 0) or 0) |
| 16463 | read_only | leverage = float(pos_data.get("leverage", 1) or 1) |
| 16466 | read_only | entry_margin = float(pos_data.get("margin", 0) or pos_data.get("initial_margin", 0) or 0) |
| 16468 | read_only | entry_margin = float(pos_data.get("notional", 0) or 0) / max(1.0, leverage) |
| 16471 | read_only | regime_raw = redis.get(f"regime:{symbol}") |
| 16478 | read_only | move_regime = str(regime.get("move_regime", "UNKNOWN")).upper() |
| 16479 | read_only | trend_dir = str(regime.get("trend_direction", "NEUTRAL")).upper() |
| 16497 | read_only | _ph = redis.hgetall(f"prediction:{symbol}:{tf}") |
| 16502 | read_only | _pdir = str(_pd.get("direction", "") or "").upper() |
| 16503 | read_only | _pconf = float(_pd.get("confidence", 0) or 0) |
| 16545 | read_only | redis.setex(cd_key, int(FAVORABLE_ADD_MARGIN_COOLDOWN_S), str(now)) |
| 16567 | read_only | position_side = position.get('side', '') |
| 16568 | read_only | position_size = abs(position.get('size', 0)) |
| 16569 | read_only | current_roi = position.get('roi', 0) |
| 16665 | read_only | """Delegate to GPUForcedPPO's ATR lookup (which reads unified_features/NATR from Redis).""" |
| 16669 | read_only | # ppo_model not ready yet — try direct Redis as last resort |
| 16671 | read_only | rc = getattr(self, "redis", None) or getattr(self, "_signal_redis", None) |
| 16673 | read_only | uf = rc.hgetall(f"unified_features:{str(symbol).upper().strip()}:5m") or {} |
| 16678 | read_only | v = float(uf.get(k, 0) or 0) |
| 16698 | read_only | # Be resilient across init variants: some paths use self.redis, others self._signal_redis |
| 16699 | read_only | redis_client = getattr(self, 'redis', None) or getattr(self, '_signal_redis', None) |
| 16700 | read_only | if not redis_client: |
| 16703 | read_only | last_warn = int(getattr(self, '_hedge_build_no_redis_warn_ts', 0) or 0) |
| 16705 | read_only | self._hedge_build_no_redis_warn_ts = now_s |
| 16706 | read_only | logger.warning("[HEDGE_BUILD] No Redis client available for feedback poll") |
| 16715 | read_only | entries = redis_client.xread({stream_key: last_id}, count=50, block=None) |
| 16737 | read_only | raw_data = data.get(b'data') or data.get('data') or '{}' |
| 16741 | read_only | event_type = payload.get('event_type') |
| 16743 | read_only | symbol = payload.get('symbol') |
| 16744 | read_only | side = payload.get('side') |
| 16745 | read_only | account = payload.get('account_id', payload.get('account', 'unknown')) |
| 16751 | read_only | payload.get('realized_pnl_usd') |
| 16752 | read_only | or payload.get('pnl_usd') |
| 16753 | read_only | or payload.get('realized_pnl') |
| 16791 | read_only | conf = float(payload.get('confidence') or payload.get('signal_confidence') or 0.0) |
| 16804 | read_only | payload.get("pnl_pct") is not None |
| 16805 | read_only | or payload.get("realized_pnl_pct") is not None |
| 16806 | read_only | or payload.get("roe_pct") is not None |
| 16810 | read_only | payload.get("realized_pnl_usd") is not None |
| 16811 | read_only | or payload.get("pnl_usd") is not None |
| 16812 | read_only | or payload.get("realized_pnl") is not None |
| 16833 | read_only | used = int(counts.get(acct, 0) or 0) |
| 16837 | read_only | credit = (getattr(self, '_profit_trim_credit_usd', {}) or {}).get(acct, 0.0) or 0.0 |
| 16873 | read_only | # Fallback: Redis hash (best-effort) |
| 16875 | read_only | raw = redis_client.hgetall(f"portfolio:positions:{acct}") or {} |
| 16903 | read_only | s = str(p.get('symbol') or '').upper().strip() |
| 16904 | read_only | sd = str(p.get('side') or p.get('positionSide') or '').upper().strip() |
| 16906 | write_metric | sides_by_symbol.setdefault(s, set()).add(sd) |
| 16920 | read_only | return float(pp.get(key) or 0.0) |
| 16929 | read_only | return float(pp.get(key) or 0.0) |
| 16939 | read_only | s = str(p.get('symbol') or '').upper().strip() |
| 16940 | read_only | sd = str(p.get('side') or p.get('positionSide') or '').upper().strip() |
| 16951 | write_metric | if (not bool(PROFIT_TRIM_ALLOW_TRIM_HEDGED_PAIRS)) and len(sides_by_symbol.get(s, set())) >= 2: |
| 16961 | read_only | s = str(p.get('symbol') or '').upper().strip() |
| 16962 | read_only | sd = str(p.get('side') or p.get('positionSide') or '').upper().strip() |
| 16972 | write_metric | if (not bool(PROFIT_TRIM_ALLOW_TRIM_HEDGED_PAIRS)) and len(sides_by_symbol.get(s, set())) >= 2: |
| 16981 | read_only | target_sym = str(candidate.get('symbol') or '').upper().strip() |
| 16982 | read_only | target_side = str(candidate.get('side') or candidate.get('positionSide') or '').upper().strip() |
| 17026 | write_signal | built = self._publish_signal_payload(trim_payload, contract_required=False) |
| 17033 | write_metric | # Spend credit only on successful publish |
| 17059 | read_only | redis_client = getattr(self, 'redis', None) or getattr(self, '_signal_redis', None) |
| 17060 | read_only | if not redis_client: |
| 17061 | read_only | logger.warning(f"[HEDGE_BUILD] No Redis client for {symbol}") |
| 17076 | read_only | redis_client.setex(key, HEDGE_BUILD_TTL_SECONDS, json.dumps(state)) |
| 17082 | read_only | redis_client.setex(legacy_key, HEDGE_BUILD_TTL_SECONDS, json.dumps(state)) |
| 17098 | read_only | redis_client = getattr(self, 'redis', None) |
| 17099 | read_only | if not redis_client: |
| 17103 | read_only | state = redis_client.get(key) |
| 17108 | write_signal | def _publish_signal_payload(self, payload: dict, *, stream: str = None, contract_required: bool = True): |
| 17109 | write_signal | """Delegate to ppo_model's _publish_signal_payload method. |
| 17111 | write_signal | This wrapper enables HybridTrainer methods to call signal publishing |
| 17115 | write_signal | return self.ppo_model._publish_signal_payload(payload, stream=stream, contract_required=contract_required) |
| 17117 | write_signal | logger.warning("[PUBLISH] Cannot publish signal - ppo_model not initialized") |
| 17120 | write_signal | def _publish_signal_unified(self, payload: dict, *, stream: str = None, contract_required: bool = True): |
| 17122 | write_metric | Unified publisher for non-GPU modules (URC / hedge builders / flash hedge / harvest). |
| 17125 | write_signal | - When ORCHESTRATOR_WORKER_MODE=publish, route ALL signals through _emit_proposal() |
| 17127 | write_metric | - When ORCHESTRATOR_WORKER_MODE=shadow or disabled, use legacy publish path. |
| 17130 | write_metric | - In publish mode, NO FALLBACK to direct publish. |
| 17134 | read_only | if not payload.get("structural_regime"): |
| 17135 | read_only | structural = self._get_structural_regime_context(str(payload.get("symbol") or "")) |
| 17136 | read_only | payload["structural_regime"] = structural.get("effective_regime") |
| 17137 | read_only | payload["macro_regime"] = structural.get("macro_regime") |
| 17138 | read_only | payload["structural_time_in_state_days"] = structural.get("time_in_state_days") |
| 17139 | read_only | payload["structural_metrics"] = structural.get("metrics") |
| 17140 | read_only | payload["risk_mode"] = structural.get("risk_mode") |
| 17156 | read_only | action = str(payload.get("action") or payload.get("action_name") or "").upper() |
| 17157 | read_only | category_hint = str(payload.get("action_category") or payload.get("category") or "").upper() |
| 17158 | read_only | hedge_mode = str(payload.get("hedge_mode") or "").upper() |
| 17161 | read_only | or payload.get("hedge_intent") |
| 17162 | read_only | or payload.get("ecf_signal") |
| 17169 | write_metric | # Feb 2026: HEDGE_DIRECT_PUBLISH_BYPASS default is now FALSE. |
| 17178 | write_metric | HEDGE_DIRECT_PUBLISH_BYPASS_ENABLED, |
| 17179 | write_metric | HEDGE_DIRECT_PUBLISH_BYPASS_MIN_CONF, |
| 17189 | write_metric | HEDGE_DIRECT_PUBLISH_BYPASS_ENABLED = False |
| 17190 | write_metric | HEDGE_DIRECT_PUBLISH_BYPASS_MIN_CONF = 0.95 |
| 17213 | read_only | bool(payload.get("risk_reducing")) |
| 17217 | read_only | _urgency_chk = str(payload.get("urgency") or "").upper() |
| 17222 | read_only | # Check orchestrator liveness from Redis |
| 17226 | read_only | getattr(self, "_signal_redis", None) |
| 17227 | read_only | or getattr(self, "redis", None) |
| 17228 | read_only | or getattr(getattr(self, "ppo_model", None), "_signal_redis", None) |
| 17231 | read_only | _hb_raw = _rc.get("orchestrator:heartbeat_ms") |
| 17251 | write_metric | # direct publish is emergency-only; conf-based bypass permanently disabled |
| 17257 | write_metric | # Respect per-account scoping when present; otherwise publish to both accounts. |
| 17258 | read_only | requested_acct = payload.get("account_id") or payload.get("account") or payload.get("target_account_id") |
| 17272 | read_only | s = SIGNAL_STREAM_PER_ACCOUNT.get(str(acct).strip().lower()) |
| 17279 | write_metric | # Pair-cap clamp for direct publish (avoid trader-side CAP blocks) |
| 17304 | read_only | sym = str(payload.get("symbol") or "").upper().strip() |
| 17308 | read_only | acct_caps = (PER_ACCOUNT_PAIR_CAPS or {}).get(acct, {}) if isinstance(PER_ACCOUNT_PAIR_CAPS, dict) else {} |
| 17309 | read_only | base_cap = float(acct_caps.get("max_margin_usd") or STACK_OPEN_MAX_MARGIN_USD or 300.0) |
| 17310 | read_only | pct = float(acct_caps.get("max_equity_pct") or STACK_OPEN_MAX_EQUITY_PCT or 0.10) |
| 17312 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 17316 | read_only | eq_raw = rc.get(f"portfolio:equity:{acct}") |
| 17321 | read_only | (eqj or {}).get("wallet_balance_usd") |
| 17322 | read_only | or (eqj or {}).get("wallet_balance") |
| 17323 | read_only | or (eqj or {}).get("balance") |
| 17329 | read_only | eq_basis = float((eqj or {}).get("equity_usd") or (eqj or {}).get("margin_balance_usd") or wallet or 0.0) |
| 17335 | write_metric | sym_is_tier3 = bool(sym and sym in set(TIER3_SYMBOLS or [])) |
| 17344 | read_only | raw_long = rc.hget(pos_key, f"{sym}:LONG") |
| 17345 | read_only | raw_short = rc.hget(pos_key, f"{sym}:SHORT") |
| 17352 | read_only | m = float(d.get("margin_used") or d.get("initialMargin") or 0.0) |
| 17360 | write_metric | if bool(MANUAL_HEDGE_PAIR_CAP_OVERRIDE_ENABLED) and sym not in set(MANUAL_HEDGE_PAIR_CAP_EXCLUDE_SYMBOLS or []): |
| 17363 | read_only | if float(leg_margins.get(leg_side, 0.0)) <= 0.0: |
| 17365 | read_only | raw_origin = rc.get(f"{POSITION_ORIGIN_KEY_PREFIX}:{acct}:{sym}:{leg_side}") if rc else None |
| 17369 | read_only | origin_val = json.loads(raw_origin).get("origin") if isinstance(raw_origin, str) else None |
| 17372 | read_only | if str(origin_val or "").lower() == "manual" and float(leg_margins.get(leg_side, 0.0)) > float(cap): |
| 17383 | read_only | mreq = float(payload.get("margin_usd", 0.0) or 0.0) |
| 17388 | read_only | notional = float(payload.get("notional_usd", 0.0) or 0.0) |
| 17392 | read_only | lev = float(payload.get("leverage", payload.get("recommended_leverage", 10)) or 10.0) |
| 17402 | write_metric | f"⚠️ [HEDGE_DIRECT_PUBLISH] No headroom for {acct}:{sym} cap={cap:.2f} existing={existing_margin:.2f}; routing to orchestrator" |
| 17404 | read_only | source = payload.get("source") or payload.get("source_module") or "trainer_unified" |
| 17407 | read_only | if payload.get("ecf_signal") or "ECF" in action: |
| 17425 | read_only | payload["margin_usd"] = float(payload.get("margin_usd", mreq) or mreq) * scale |
| 17429 | read_only | payload["notional_usd"] = float(payload.get("notional_usd", 0.0) or 0.0) * scale |
| 17433 | read_only | payload["position_size_pct"] = float(payload.get("position_size_pct", 0.0) or 0.0) * scale |
| 17437 | write_metric | logger.debug(f"[HEDGE_DIRECT_PUBLISH] pair-cap clamp failed: {clamp_err}") |
| 17445 | write_metric | "⚡ [HEDGE_DIRECT_PUBLISH] %s %s reason=%s streams=%s", |
| 17446 | read_only | payload.get("symbol"), action, _bypass_reason, direct_stream, |
| 17448 | write_signal | return self._publish_signal_payload(payload, stream=direct_stream, contract_required=contract_required) |
| 17450 | read_only | source = payload.get("source") or payload.get("source_module") or "trainer_unified" |
| 17455 | read_only | if payload.get("ecf_signal") or "ECF" in action: |
| 17468 | write_metric | if ORCHESTRATOR_WORKER_ENABLED and str(ORCHESTRATOR_WORKER_MODE).lower() == "publish": |
| 17469 | write_signal | # In publish mode, ALL signals go through orchestrator |
| 17471 | read_only | source = payload.get("source") or payload.get("source_module") or "trainer_unified" |
| 17472 | read_only | category = payload.get("action_category") or payload.get("category") or "" |
| 17476 | read_only | if payload.get("fastlane") or payload.get("bypass_validation"): |
| 17478 | read_only | if "SHIELD" in str(payload.get("hedge_mode") or "").upper(): |
| 17480 | read_only | if payload.get("ecf_signal") or "ECF" in str(payload.get("action") or "").upper(): |
| 17495 | write_metric | # LEGACY MODE: Use buffered pipeline or direct publish |
| 17498 | write_metric | from config import UNIFY_NON_GPU_PUBLISH_THROUGH_BUFFERED |
| 17500 | write_metric | UNIFY_NON_GPU_PUBLISH_THROUGH_BUFFERED = False |
| 17502 | write_metric | # Preferred: publish via buffered pipeline (single publisher surface). |
| 17503 | write_metric | if bool(UNIFY_NON_GPU_PUBLISH_THROUGH_BUFFERED): |
| 17505 | write_signal | if hasattr(self, "ppo_model") and self.ppo_model is not None and hasattr(self.ppo_model, "_publish_buffered_signals"): |
| 17506 | write_signal | # Ensure stream override is carried (buffered publisher supports per-payload stream via SIGNAL_OUTPUT_STREAM). |
| 17510 | write_signal | # _publish_buffered_signals returns count |
| 17511 | write_signal | n = int(self.ppo_model._publish_buffered_signals([p2]) or 0) |
| 17514 | write_metric | logger.debug(f"[PUBLISH_UNIFIED] buffered publish failed (fallback to direct): {e}") |
| 17516 | write_metric | # Fallback: direct publish (legacy - only in shadow mode) |
| 17517 | write_signal | return self._publish_signal_payload(payload, stream=stream, contract_required=contract_required) |
| 17530 | write_metric | THIS IS THE ONLY WAY MODULES SHOULD PUBLISH IN ORCHESTRATOR_WORKER_MODE=publish. |
| 17532 | write_metric | NO FALLBACK TO DIRECT PUBLISH. |
| 17542 | write_metric | Does NOT fall back to direct publish. |
| 17555 | read_only | # Get Redis client |
| 17556 | read_only | redis_client = ( |
| 17557 | read_only | getattr(self, "_signal_redis", None) |
| 17558 | read_only | or getattr(self, "redis", None) |
| 17559 | read_only | or getattr(getattr(self, "ppo_model", None), "_signal_redis", None) |
| 17560 | read_only | or getattr(getattr(self, "ppo_model", None), "redis", None) |
| 17563 | read_only | if redis_client is None: |
| 17564 | read_only | logger.error(f"[EMIT_PROPOSAL] No Redis client available - cannot emit proposal") |
| 17600 | read_only | def _meta_get(key: str): |
| 17602 | read_only | md = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {} |
| 17604 | read_only | if payload.get(key) is not None: |
| 17605 | read_only | return payload.get(key) |
| 17606 | read_only | if md.get(key) is not None: |
| 17607 | read_only | return md.get(key) |
| 17611 | read_only | for alias in (aliases.get(key) or []): |
| 17613 | read_only | if payload.get(alias) is not None: |
| 17614 | read_only | return payload.get(alias) |
| 17615 | read_only | if md.get(alias) is not None: |
| 17616 | read_only | return md.get(alias) |
| 17621 | read_only | if payload.get(tf_key) is not None: |
| 17622 | read_only | return payload.get(tf_key) |
| 17623 | read_only | if md.get(tf_key) is not None: |
| 17624 | read_only | return md.get(tf_key) |
| 17636 | read_only | act_u = str(payload.get("action") or payload.get("action_name") or "").upper().strip() |
| 17637 | read_only | cat_u = str(payload.get("action_category") or payload.get("category") or "").upper().strip() |
| 17638 | read_only | sym_u = str(payload.get("symbol") or "").upper().strip() |
| 17659 | write_metric | self._publish_exec_event( |
| 17661 | read_only | account_id=str(payload.get("account_id") or "primary"), |
| 17677 | read_only | if TRAINER_CLAMP_PROPOSAL_CONFIDENCE and (payload.get("confidence") is not None or payload.get("model_confidence") is not None): |
| 17678 | read_only | conf_raw = float(payload.get("confidence", payload.get("model_confidence", 0.0)) or 0.0) |
| 17690 | read_only | str(payload.get("symbol") or ""), |
| 17700 | read_only | if not payload.get("decision_id"): |
| 17701 | read_only | sym0 = str(payload.get("symbol") or "").upper().strip() or "UNKNOWN" |
| 17702 | read_only | tf0 = str(payload.get("timeframe") or payload.get("tf") or "na").lower().strip() or "na" |
| 17724 | write_metric | self._publish_exec_event( |
| 17726 | read_only | account_id=str(payload.get("account_id") or "primary"), |
| 17727 | read_only | symbol=str(payload.get("symbol") or "").upper(), |
| 17734 | read_only | act_u = str(payload.get("action") or payload.get("action_name") or "").upper().strip() |
| 17742 | read_only | if not _has_value(_meta_get(str(k))): |
| 17745 | read_only | if not _has_value(_meta_get(str(k))): |
| 17747 | read_only | if bool(TRAINER_SOURCE_REQUIRE_DECISION_ID_FOR_OPEN_RISK) and not _has_value(payload.get("decision_id")): |
| 17753 | read_only | _src_tf_votes = _meta_get("tf_votes") |
| 17754 | read_only | _src_bias_dir = _meta_get("bias_dir") |
| 17755 | read_only | _src_timing_dir = _meta_get("timing_dir") |
| 17780 | read_only | str(payload.get("symbol") or "").upper(), |
| 17787 | write_metric | self._publish_exec_event( |
| 17789 | read_only | account_id=str(payload.get("account_id") or "primary"), |
| 17790 | read_only | symbol=str(payload.get("symbol") or "").upper(), |
| 17796 | read_only | "decision_id": str(payload.get("decision_id") or ""), |
| 17805 | read_only | act_u2 = str(payload.get("action") or payload.get("action_name") or "").upper().strip() |
| 17806 | read_only | cat_u2 = str(payload.get("action_category") or payload.get("category") or "").upper().strip() |
| 17811 | read_only | md = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {} |
| 17813 | read_only | dq_source_ok = payload.get("dq_source_ok") or md.get("dq_source_ok") |
| 17814 | read_only | dq_ob_age = payload.get("dq_orderbook_age_ms") or md.get("dq_orderbook_age_ms") |
| 17815 | read_only | dq_liq_age = payload.get("dq_liqmap_age_ms") or md.get("dq_liqmap_age_ms") |
| 17828 | read_only | feat_age = payload.get("features_age_ms") or md.get("features_age_ms") |
| 17829 | read_only | feat_ts = payload.get("features_ts_ms") or md.get("features_ts_ms") or payload.get("feature_ts_ms") or md.get("feature_ts_ms") |
| 17835 | read_only | # Best-effort Redis probe for unified_features ts_ms (5m) if missing. |
| 17837 | read_only | if feat_age is None and getattr(self, "redis", None): |
| 17838 | read_only | sym_u = str(payload.get("symbol") or "").upper().strip() |
| 17840 | read_only | raw_ts = self.redis.hget(f"unified_features:{sym_u}:5m", "ts_ms")  # type: ignore[attr-defined] |
| 17842 | read_only | raw_ts = self.redis.hget(f"unified_features:{sym_u}:5m", "timestamp")  # type: ignore[attr-defined] |
| 17872 | read_only | _r_stress = str(payload.get("regime_stress") or md.get("regime_stress") or "").upper().strip() |
| 17873 | read_only | _r_risk = str(payload.get("structural_risk_mode") or md.get("structural_risk_mode") or md.get("risk_mode") or "").upper().strip() |
| 17895 | read_only | str(payload.get("symbol") or "").upper(), old_act, _regime_block_reason, |
| 17898 | write_metric | self._publish_exec_event( |
| 17900 | read_only | account_id=str(payload.get("account_id") or "primary"), |
| 17901 | read_only | symbol=str(payload.get("symbol") or "").upper(), |
| 17913 | read_only | sym = str(payload.get("symbol") or "").strip().upper() |
| 17917 | read_only | meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {} |
| 17920 | read_only | if not payload.get("signal_id"): |
| 17922 | read_only | sid = meta.get("signal_id") or meta.get("id") or meta.get("_proposal_id") |
| 17927 | read_only | sid = payload.get("proposal_id") |
| 17932 | read_only | if not payload.get("timeframe"): |
| 17934 | read_only | tf = meta.get("timeframe") or meta.get("tf") or meta.get("interval") |
| 17941 | read_only | ob_ts = int(payload.get("orderbook_ts_ms") or 0) |
| 17948 | read_only | msnap = redis_client.hgetall(f"msnap:coinapi_wsds:{sym}") or {} |
| 17957 | read_only | ob_ts = int(float(msnap.get("updated_ts_ms", 0) or 0)) |
| 17964 | read_only | ob_raw = redis_client.get(f"orderbook:top:{sym}") |
| 17971 | read_only | ob.get("updated_ts_ms") |
| 17972 | read_only | or ob.get("ts_ms") |
| 17973 | read_only | or ob.get("timestamp") |
| 17974 | read_only | or ob.get("ts") |
| 17987 | read_only | lm_ts = int(payload.get("liqmap_ts_ms") or 0) |
| 18002 | read_only | ts_raw = redis_client.hget(f"unified_features:{sym}:{tf}", "liquidation_updated_ts") |
| 18056 | read_only | last = float(self._dq_watchdog_last_ts.get(sym, 0.0) or 0.0) |
| 18093 | read_only | msnap = redis_client.hgetall(f"msnap:coinapi_wsds:{sym}") or {} |
| 18102 | read_only | ob_ts = int(float(msnap.get("updated_ts_ms", 0) or 0)) |
| 18107 | read_only | ob_raw = redis_client.get(f"orderbook:top:{sym}") |
| 18114 | read_only | ob.get("updated_ts_ms") |
| 18115 | read_only | or ob.get("ts_ms") |
| 18116 | read_only | or ob.get("timestamp") |
| 18117 | read_only | or ob.get("ts") |
| 18140 | read_only | ts_raw = redis_client.hget(f"unified_features:{sym}:{tf}", "liquidation_updated_ts") |
| 18164 | read_only | enrich_proposal_with_trainer(redis_client, _p_dict) |
| 18190 | read_only | _ta_result = get_ta_direction_cached(redis_client, _ta_sym) |
| 18198 | read_only | proposal.metadata["ta_direction"] = _ta_result.get("direction", 0) |
| 18199 | read_only | proposal.metadata["ta_strength"] = _ta_result.get("strength", 0.0) |
| 18200 | read_only | proposal.metadata["ta_htf_bias"] = _ta_result.get("htf_bias", 0) |
| 18201 | read_only | proposal.metadata["ta_gate_reason"] = _ta_gate.get("reason", "") |
| 18202 | read_only | proposal.metadata["ta_gate_allowed"] = _ta_gate.get("allowed", True) |
| 18209 | read_only | _ta_result.get("direction"), _ta_result.get("strength", 0), |
| 18210 | read_only | _ta_result.get("htf_bias"), _ta_gate.get("reason"), |
| 18224 | write_metric | self._publish_exec_event( |
| 18230 | read_only | "ta_direction": _ta_result.get("direction", 0), |
| 18231 | read_only | "ta_strength": _ta_result.get("strength", 0), |
| 18232 | read_only | "ta_htf_bias": _ta_result.get("htf_bias", 0), |
| 18233 | read_only | "ta_details": str(_ta_result.get("per_tf", {}))[:500], |
| 18235 | read_only | "gate_reason": _ta_gate.get("reason", ""), |
| 18242 | read_only | _adj_conf = _ta_gate.get("adjusted_confidence", float(getattr(proposal, "confidence", 0.5) or 0.5)) |
| 18246 | read_only | if _ta_gate.get("reason") == "TA_ALIGNED": |
| 18249 | read_only | _ta_sym, _proposal_act, _ta_result.get("direction"), |
| 18250 | read_only | _ta_result.get("strength", 0), |
| 18258 | read_only | success = emit_proposal_to_stream(redis_client, proposal, stream=stream) |
| 18279 | write_checkpoint_metadata | def _publish_skip_event(self, payload: dict, reason_code: str, reason_detail: str): |
| 18280 | write_checkpoint_metadata | """Delegate to ppo_model's _publish_skip_event method.""" |
| 18282 | write_checkpoint_metadata | return self.ppo_model._publish_skip_event(payload, reason_code, reason_detail) |
| 18284 | write_checkpoint_metadata | logger.debug(f"[SKIP_EVENT] Cannot publish - ppo_model not initialized: {reason_code}") |
| 18286 | write_metric | def _publish_exec_event( |
| 18295 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 18313 | write_metric | rc.xadd( |
| 18316 | read_only | maxlen=int(self._exec_event_maxlen), |
| 18322 | write_metric | def _maybe_emit_canary(self, *, published_count: int, cycle_count: int) -> None: |
| 18324 | write_signal | from config import ENABLE_CANARY_SIGNALS, CANARY_INTERVAL_SEC, CANARY_ZERO_PUBLISH_CYCLES, TRADING_ACCOUNTS |
| 18328 | write_metric | CANARY_ZERO_PUBLISH_CYCLES = 5 |
| 18336 | write_metric | if int(published_count or 0) <= 0: |
| 18337 | write_metric | self._canary_zero_publish_cycles += 1 |
| 18339 | write_metric | self._canary_zero_publish_cycles = 0 |
| 18342 | write_metric | zero_due = bool(self._canary_zero_publish_cycles >= int(CANARY_ZERO_PUBLISH_CYCLES)) |
| 18347 | write_metric | self._canary_zero_publish_cycles = 0 |
| 18446 | read_only | - 'pnl_pct': Used by trader/Redis position storage |
| 18455 | read_only | # Try pnl_pct first (trader/Redis standard) |
| 18456 | read_only | pnl_pct = position.get('pnl_pct') |
| 18464 | read_only | pnl_percentage = position.get('pnl_percentage') |
| 18473 | read_only | unrealized_pnl = float(position.get('unrealized_pnl', 0) or 0) |
| 18474 | read_only | entry_price = float(position.get('entry_price', 0) or 0) |
| 18475 | read_only | size = float(position.get('size', 0) or 0) |
| 18476 | read_only | leverage = float(position.get('leverage', 1) or 1) |
| 18735 | read_only | trigger_dir = stack['trigger'].get('direction', 'NEUTRAL') |
| 18772 | read_only | redis_client = getattr(self, 'redis', None) or getattr(self, '_signal_redis', None) |
| 18773 | read_only | if not redis_client or not symbol: |
| 18790 | read_only | if key in mapping and mapping.get(key) not in (None, ''): |
| 18791 | read_only | return float(mapping.get(key)) |
| 18798 | read_only | snap = get_source_router(redis_client).get_snapshot_or_default(symbol) |
| 18819 | read_only | feat = _decode_hash(redis_client.hgetall(f'unified_features:{symbol}:{tf}')) |
| 18863 | read_only | quality = max(0.0, min(1.0, float(ctx.get('quality_score', 0.0) or 0.0))) |
| 18864 | read_only | spoof = max(0.0, min(1.0, float(ctx.get('spoof_score', 0.0) or 0.0))) |
| 18865 | read_only | fast = max(0.0, min(1.0, float(ctx.get('fast_move_score', 0.0) or 0.0))) |
| 18866 | read_only | churn = max(0.0, min(1.0, float(ctx.get('churn_score', 0.0) or 0.0))) |
| 18867 | read_only | false_move = max(0.0, min(1.0, float(ctx.get('false_move_score', 0.0) or 0.0))) |
| 18868 | read_only | trend_strength = min(1.0, max(abs(float(ctx.get('ret_15m', 0.0) or 0.0)), abs(float(ctx.get('ret_1h', 0.0) or 0.0))) * 4.0) |
| 18869 | read_only | liq_total = abs(float(ctx.get('liq_long', 0.0) or 0.0)) + abs(float(ctx.get('liq_short', 0.0) or 0.0)) |
| 18870 | read_only | liq_imbalance = abs(float(ctx.get('liq_long', 0.0) or 0.0) - float(ctx.get('liq_short', 0.0) or 0.0)) / max(liq_total, 1.0) |
| 18871 | read_only | funding_basis = min(1.0, abs(float(ctx.get('funding_rate', 0.0) or 0.0)) * 50.0 + abs(float(ctx.get('basis_pct', 0.0) or 0.0)) * 4.0) |
| 18909 | read_only | if self._signal_redis: |
| 18910 | read_only | # Check Redis for cooldown key |
| 18911 | read_only | ttl = self._signal_redis.ttl(cooldown_key) |
| 18914 | read_only | expiry_ts = self._cooldown_cache.get(cooldown_key, 0) |
| 18927 | read_only | def _check_budget(self, symbol: str, category: str) -> Tuple[bool, str]: |
| 18949 | read_only | if self._signal_redis: |
| 18950 | read_only | per_symbol_count = int(self._signal_redis.get(per_symbol_key) or 0) |
| 18952 | read_only | per_symbol_count = self._budget_counters.get(per_symbol_key, 0) |
| 18962 | read_only | if self._signal_redis: |
| 18963 | read_only | global_count = int(self._signal_redis.get(global_key) or 0) |
| 18965 | read_only | global_count = self._budget_counters.get(global_key, 0) |
| 18976 | write_signal | """Increment Redis budget counters with 3600s TTL after signal published.""" |
| 18988 | read_only | if self._signal_redis: |
| 18990 | read_only | pipe = self._signal_redis.pipeline() |
| 18998 | read_only | self._budget_counters[per_symbol_key] = self._budget_counters.get(per_symbol_key, 0) + 1 |
| 18999 | read_only | self._budget_counters[global_key] = self._budget_counters.get(global_key, 0) + 1 |
| 19005 | write_signal | """Set cooldown key in Redis after OPEN_RISK signal published.""" |
| 19020 | read_only | if self._signal_redis: |
| 19021 | read_only | self._signal_redis.setex(cooldown_key, cooldown_seconds, "1") |
| 19041 | read_only | if not self._signal_redis: |
| 19047 | read_only | messages = self._signal_redis.xread({feedback_stream: '0-0'}, count=100, block=0) |
| 19051 | read_only | event_type = data.get(b'event_type', b'').decode('utf-8') |
| 19054 | read_only | symbol = data.get(b'symbol', b'').decode('utf-8') |
| 19055 | read_only | side = data.get(b'side', b'').decode('utf-8') |
| 19056 | read_only | pnl = float(data.get(b'pnl', 0)) |
| 19062 | write_signal | self._signal_redis.xdel(feedback_stream, msg_id) |
| 19084 | read_only | # Persist to Redis as well (canonical HEDGE_BUILD signal for gating + dashboards) |
| 19086 | read_only | redis_client = getattr(self, 'redis', None) or getattr(self, '_signal_redis', None) |
| 19087 | read_only | if redis_client: |
| 19097 | read_only | redis_client.setex(key, int(ttl_sec), json.dumps(state)) |
| 19114 | read_only | # Canonical: Redis-backed key set by _enter_hedge_build_state (triggered via trader feedback) |
| 19116 | read_only | redis_client = getattr(self, 'redis', None) or getattr(self, '_signal_redis', None) |
| 19117 | read_only | if redis_client: |
| 19131 | read_only | raw = redis_client.get(key) |
| 19145 | read_only | return True, str(state.get('reason') or state.get('event_type') or 'feedback') |
| 19154 | read_only | state = self._hedge_build_state.get(symbol) |
| 19156 | read_only | if not state or not state.get('active'): |
| 19169 | read_only | return True, str(state.get('reason') or state.get('event_type') or 'hedge_build') |
| 19281 | read_only | if not self._signal_redis: |
| 19283 | read_only | return (no_data_action if no_data_action in ('PASS', 'DELAY') else 'DELAY'), 'MICROSTRUCTURE_FAIL_CLOSED (no_redis)' |
| 19286 | read_only | source_count = int(ctx.get('source_count', 0) or 0) |
| 19293 | read_only | spread_pct = max(0.0, float(ctx.get('spread_pct', 0.0) or 0.0)) |
| 19294 | read_only | spoof_score = max(0.0, min(1.0, float(ctx.get('spoof_score', 0.0) or 0.0))) |
| 19295 | read_only | fast_move = max(0.0, min(1.0, float(ctx.get('fast_move_score', 0.0) or 0.0))) |
| 19296 | read_only | churn_score = max(0.0, min(1.0, float(ctx.get('churn_score', 0.0) or 0.0))) |
| 19297 | read_only | quality_score = max(0.0, min(1.0, float(ctx.get('quality_score', 0.0) or 0.0))) |
| 19298 | read_only | false_move = max(0.0, min(1.0, float(ctx.get('false_move_score', 0.0) or 0.0))) |
| 19299 | read_only | liq_total = abs(float(ctx.get('liq_long', 0.0) or 0.0)) + abs(float(ctx.get('liq_short', 0.0) or 0.0)) |
| 19300 | read_only | liq_imbalance = abs(float(ctx.get('liq_long', 0.0) or 0.0) - float(ctx.get('liq_short', 0.0) or 0.0)) / max(liq_total, 1.0) |
| 19301 | read_only | regime_vol = min(1.0, max(abs(float(ctx.get('ret_5m', 0.0) or 0.0)), abs(float(ctx.get('ret_15m', 0.0) or 0.0)) * 0.8, abs(float(ctx.get('ret_1h', 0.0) or 0.0)) * 0.5) * 5.0) |
| 19333 | read_only | f"healthy src={ctx.get('source', 'none')} sources={source_count} quality={quality_score:.2f} " |
| 19446 | read_only | state_manager = get_signal_state_manager(getattr(self, '_signal_redis', None)) |
| 19451 | read_only | f"allowed={stats.get('signals_allowed', 0)} / " |
| 19452 | read_only | f"blocked={stats.get('signals_blocked', 0)} / " |
| 19453 | read_only | f"block_rate={stats.get('block_rate_pct', 0):.1f}% / " |
| 19454 | read_only | f"by_pending={stats.get('blocked_by_pending', 0)} / " |
| 19455 | read_only | f"by_cooldown={stats.get('blocked_by_cooldown', 0)} / " |
| 19456 | read_only | f"by_duplicate={stats.get('blocked_by_duplicate', 0)} / " |
| 19457 | read_only | f"override_price={stats.get('overridden_by_price', 0)} / " |
| 19458 | read_only | f"override_pnl={stats.get('overridden_by_pnl', 0)} / " |
| 19459 | read_only | f"override_position={stats.get('overridden_by_position', 0)}" |
| 19467 | write_risk_state | """I) Risk Gates - Hard constraints that block publishing/execution |
| 19555 | read_only | st.get("margin_utilization_pct", st.get("margin_utilization", st.get("margin_ratio", 0.0))) |
| 19570 | read_only | margin_util = float(self._margin_metrics.get('margin_utilization', 0.0) or 0.0) |
| 19647 | read_only | "spread_pct": liquidity_result.get("spread_pct"), |
| 19648 | read_only | "depth_usd": liquidity_result.get("depth_usd"), |
| 19649 | read_only | "orderbook_ts_ms": liquidity_result.get("orderbook_ts_ms"), |
| 19650 | read_only | "min_depth_usd": liquidity_result.get("min_depth_usd"), |
| 19651 | read_only | "warn_depth_usd": liquidity_result.get("warn_depth_usd"), |
| 19652 | read_only | "max_spread_pct": liquidity_result.get("max_spread_pct"), |
| 19653 | read_only | "warn_spread_pct": liquidity_result.get("warn_spread_pct"), |
| 19654 | read_only | "liq_tier": liquidity_result.get("liq_tier"), |
| 19655 | read_only | "regime_stress": liquidity_result.get("regime_stress"), |
| 19656 | read_only | "regime_structure": liquidity_result.get("regime_structure"), |
| 19657 | read_only | "structural_regime": liquidity_result.get("structural_regime"), |
| 19674 | read_only | "spread_pct": liquidity_result.get("spread_pct"), |
| 19675 | read_only | "depth_usd": liquidity_result.get("depth_usd"), |
| 19676 | read_only | "orderbook_ts_ms": liquidity_result.get("orderbook_ts_ms"), |
| 19677 | read_only | "min_depth_usd": liquidity_result.get("min_depth_usd"), |
| 19678 | read_only | "warn_depth_usd": liquidity_result.get("warn_depth_usd"), |
| 19679 | read_only | "max_spread_pct": liquidity_result.get("max_spread_pct"), |
| 19680 | read_only | "warn_spread_pct": liquidity_result.get("warn_spread_pct"), |
| 19681 | read_only | "liq_tier": liquidity_result.get("liq_tier"), |
| 19682 | read_only | "regime_stress": liquidity_result.get("regime_stress"), |
| 19683 | read_only | "regime_structure": liquidity_result.get("regime_structure"), |
| 19684 | read_only | "structural_regime": liquidity_result.get("structural_regime"), |
| 19697 | read_only | effective = str(structural.get("effective_regime") or "NORMAL").upper() |
| 19753 | read_only | rc = self._signal_redis if getattr(self, "_signal_redis", None) else get_redis() |
| 19788 | read_only | if pos_symbol in correlation_groups.get(symbol_group, []): |
| 19789 | read_only | gm = float(pos_rec.get("gross_margin", 0) or 0) |
| 19790 | read_only | nn = float(pos_rec.get("net_notional", 0) or 0) |
| 19824 | read_only | sym_rec = all_pos.get(symbol, {}) |
| 19825 | read_only | sym_margin_pct = (float(sym_rec.get("gross_margin", 0) or 0) / current_equity) * 100 if current_equity > 0 else 0 |
| 19839 | read_only | if pos_symbol in correlation_groups.get(symbol_group, []): |
| 19840 | read_only | pos_notional = abs(float(pos_rec.get('gross_notional', 0) or 0)) |
| 19884 | read_only | # Get order book data from Redis - prefer fresh CoinAPI WSDS msnap |
| 19888 | read_only | msnap_data = self.redis.hgetall(f"msnap:coinapi_wsds:{symbol}") or {} |
| 19893 | read_only | updated_ts_ms = int(float(msnap_data.get("updated_ts_ms", 0) or 0)) |
| 19902 | read_only | best_bid = float(msnap_data.get('best_bid_px', 0) or 0) |
| 19903 | read_only | best_ask = float(msnap_data.get('best_ask_px', 0) or 0) |
| 19910 | read_only | bid_sum_5 = float(msnap_data.get('book_bid_sum_5', 0) or 0) |
| 19911 | read_only | ask_sum_5 = float(msnap_data.get('book_ask_sum_5', 0) or 0) |
| 19931 | read_only | ob_data = self.redis.get(key_pattern) |
| 19944 | read_only | orderbook_ts_ms = int(ob.get("ts_ms") or ob.get("timestamp") or 0) or orderbook_ts_ms |
| 19949 | read_only | best_bid = float(ob.get('bid', ob.get('best_bid', 0)) or 0.0) |
| 19950 | read_only | best_ask = float(ob.get('ask', ob.get('best_ask', 0)) or 0.0) |
| 19951 | read_only | mid_price = float(ob.get('mid_px', 0) or 0.0) |
| 19955 | read_only | spread_bps = float(ob.get('spread_bps', 0.0) or 0.0) |
| 19960 | read_only | spread_pct = float(ob.get('spread_pct', 0.0) or 0.0) |
| 19961 | read_only | if spread_pct <= 0 and ob.get('spread') and mid_price > 0: |
| 19962 | read_only | spread_pct = (float(ob.get('spread', 0) or 0.0) / mid_price) * 100 |
| 19967 | read_only | bid_depth = ob.get('bid_depth', 0.0)  # USD depth on bid side |
| 19968 | read_only | ask_depth = ob.get('ask_depth', 0.0)  # USD depth on ask side |
| 19969 | read_only | total_depth = ob.get('total_depth', bid_depth + ask_depth) |
| 19984 | read_only | last_ts = float(self._last_liquidity_raw_log_ts.get(symbol, 0.0) or 0.0) |
| 20001 | read_only | ob.get('source'), |
| 20094 | read_only | axes = (self._last_regime_axes.get(symbol, {}) or {}) |
| 20097 | read_only | stress = str(axes.get("stress") or "").upper() |
| 20098 | read_only | structure = str(axes.get("structure") or "").upper() |
| 20116 | read_only | effective = str(structural.get("effective_regime") or "").upper() |
| 20289 | read_only | # Get trader-reported positions from Redis (executors) |
| 20336 | read_only | current_side = position.get('side', 'LONG') |
| 20367 | read_only | position_notional = abs(position.get('notional', 0) or 0) |
| 20386 | read_only | if pos_symbol == hedge_symbol and pos_data.get('side') == opposite_side: |
| 20437 | read_only | current_equity = portfolio.get('total_balance', 0) |
| 20442 | read_only | symbol_position = all_positions.get(symbol) |
| 20444 | read_only | position_notional = abs(symbol_position.get('notional', 0) or 0) |
| 20466 | read_only | abs(all_positions.get(s, {}).get('notional', 0) or 0) |
| 20480 | read_only | regime = market_state.get('market_regime', 'normal') |
| 20510 | read_only | current_equity = portfolio.get('total_balance', 0) |
| 20511 | read_only | margin_used = portfolio.get('total_margin_used', 0) |
| 20512 | read_only | margin_utilization = portfolio.get('margin_utilization_pct', 0) |
| 20545 | read_only | pnl_pct = pos_data.get('pnl_percentage', 0) |
| 20546 | read_only | duration_hours = pos_data.get('duration_hours', 0) |
| 20552 | read_only | 'notional': abs(pos_data.get('notional', 0) or 0) |
| 20589 | read_only | gpu_util = gpu_stats.get('gpu_util', 0.0) if isinstance(gpu_stats, dict) else 0.0 |
| 20590 | read_only | vram_util = gpu_stats.get('vram_util', 0.0) if isinstance(gpu_stats, dict) else 0.0 |
| 20653 | read_only | pos.get('unrealized_pnl', 0) for pos in self._real_positions.values() |
| 20683 | read_only | # Get order book depth from Redis |
| 20685 | read_only | ob_data = self.redis.get(ob_key) |
| 20689 | read_only | depth = ob.get('total_depth', 100000) |
| 20690 | read_only | spread = ob.get('spread_pct', 0.001) |
| 20708 | read_only | perf = self._trade_performance.get(symbol, {'wins': 0, 'losses': 0, 'total_win': 0, 'total_loss': 0}) |
| 20838 | read_only | redis_client = getattr(self, 'redis', None) or getattr(self, '_signal_redis', None) |
| 20839 | read_only | if not redis_client: |
| 20840 | read_only | return 0.015  # Default 1.5% if no Redis |
| 20844 | read_only | msnap_data = redis_client.hgetall(msnap_key) |
| 20852 | read_only | atr_pct = float(msnap_data.get('atr_pct', 0) or 0) |
| 20859 | read_only | uf = redis_client.hgetall(uf_key) or {} |
| 20863 | read_only | _atr_pct = float(uf.get("atr_pct", 0) or 0) |
| 20873 | read_only | v = float(uf.get(k, 0) or 0) |
| 20883 | read_only | ta_data = redis_client.hgetall(ta_key) |
| 20888 | read_only | atr_14 = float(ta_data.get('ta_ATR_14_5m', 0) or 0) |
| 20889 | read_only | price = float(ta_data.get('close', ta_data.get('price', 0)) or 0) |
| 20916 | read_only | ob_data = self.redis.get(ob_key) |
| 20925 | read_only | total_depth = ob.get('total_depth', 0.0) |
| 20926 | read_only | spread_pct = ob.get('spread_pct', 0.0) |
| 20959 | read_only | if not position or position.get('quantity', 0) == 0: |
| 20968 | read_only | side = position.get('side', 'LONG') |
| 20969 | read_only | entry_price = position.get('entry_price', current_price) |
| 20970 | read_only | leverage = position.get('leverage', 1.0) |
| 20971 | read_only | quantity = abs(position.get('quantity', 0)) |
| 20976 | read_only | liquidation_price = float(position.get('liquidation_price') or position.get('liquidationPrice') or 0.0) |
| 21013 | read_only | pos.get('unrealized_pnl', 0) for pos in self._real_positions.values() |
| 21064 | read_only | axes = self._last_regime_axes.get(symbol) |
| 21066 | read_only | regime_label = str(axes.get('label') or 'NORMAL').upper() |
| 21067 | read_only | stress = str(axes.get('stress') or 'LOW').upper() |
| 21124 | read_only | # Redis telemetry (optional, when ENABLE_BLEND_TELEMETRY=1) |
| 21127 | read_only | redis_client = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 21128 | read_only | if redis_client: |
| 21138 | read_only | redis_client.setex(f'rl:blend_telemetry:{symbol}', 60, _json_blend.dumps(telemetry)) |
| 21232 | read_only | """Update trainer status in Redis with enhanced description""" |
| 21236 | read_only | self.redis.setex('status:trainer', 300, enhanced_status)  # 5 minute expiry |
| 21293 | read_only | balance = float(account_info.get('totalWalletBalance', 0)) |
| 21321 | read_only | 5. Redis cache (if all external sources fail) |
| 21360 | read_only | PriceSource.REDIS_CACHE: SourceConfig( |
| 21361 | read_only | name=PriceSource.REDIS_CACHE, |
| 21372 | read_only | redis_client=self.redis, |
| 21374 | write_metric | publish_interval_ms=getattr(main_config, 'PRICE_PUBLISH_INTERVAL_MS', 100), |
| 21378 | read_only | logger.info(f"   Sources: CoinAPI(p1) → [REDACTED](p2) → CCXT(p3) → KuCoin(p4) → Redis(cache)") |
| 21406 | write_metric | # If an external price provider process is already publishing fresh `price:realtime:*`, |
| 21409 | read_only | if getattr(self, "redis", None) is not None and SYMBOLS: |
| 21411 | read_only | raw = self.redis.get(f"price:realtime:{probe}") |
| 21415 | read_only | ts_ms = int(parsed.get("received_ts_ms", 0) or parsed.get("ts_ms", 0) or 0) |
| 21512 | read_only | 'available_margin': self._margin_metrics.get('available_balance', 10000.0), |
| 21513 | read_only | 'used_margin': self._margin_metrics.get('used_margin', 0.0), |
| 21514 | read_only | 'margin_utilization': self._margin_metrics.get('margin_utilization', 0.0), |
| 21515 | read_only | 'total_margin_balance': self._margin_metrics.get('total_margin_balance', 10000.0), |
| 21516 | read_only | 'max_withdraw': self._margin_metrics.get('max_withdraw', 10000.0) |
| 21549 | read_only | accounts_data = combined_state.get('accounts', {}) |
| 21553 | read_only | positions = account_data.get('positions', []) |
| 21556 | read_only | symbol = pos_data.get('symbol', 'UNKNOWN') |
| 21557 | read_only | side = pos_data.get('side', 'UNKNOWN').upper() |
| 21574 | read_only | side = pos_data.get('side', 'UNKNOWN').upper() |
| 21585 | write_metric | # CRITICAL: Publish REAL portfolio data to Redis for traders/monitoring |
| 21588 | read_only | rc = self._signal_redis if getattr(self, "_signal_redis", None) else get_redis() |
| 21595 | read_only | 'realized_pnl_1d': combined_state.get('total_realized_pnl_1d', 0), |
| 21596 | read_only | 'realized_pnl_7d': combined_state.get('total_realized_pnl_7d', 0), |
| 21597 | read_only | 'realized_pnl_30d': combined_state.get('total_realized_pnl_30d', 0), |
| 21607 | write_metric | # Also publish per-account breakdown |
| 21608 | read_only | for acct_name, acct_data in combined_state.get('accounts', {}).items(): |
| 21611 | read_only | 'equity': acct_data.get('equity', 0), |
| 21612 | read_only | 'unrealized_pnl': acct_data.get('unrealized_pnl', 0), |
| 21613 | read_only | 'realized_pnl_1d': acct_data.get('realized_pnl_1d', 0), |
| 21614 | read_only | 'realized_pnl_7d': acct_data.get('realized_pnl_7d', 0), |
| 21615 | read_only | 'realized_pnl_30d': acct_data.get('realized_pnl_30d', 0), |
| 21616 | read_only | 'position_count': acct_data.get('position_count', 0), |
| 21621 | write_metric | logger.debug(f"[PORTFOLIO_REDIS] Published real PnL: 1d=${combined_state.get('total_realized_pnl_1d', 0):.2f}, " |
| 21622 | read_only | f"7d=${combined_state.get('total_realized_pnl_7d', 0):.2f}") |
| 21623 | read_only | except Exception as redis_err: |
| 21624 | write_metric | logger.debug(f"[PORTFOLIO_REDIS] Failed to publish: {redis_err}") |
| 21699 | read_only | 'available_margin': self._margin_metrics.get('available_balance', 10000.0), |
| 21700 | read_only | 'used_margin': self._margin_metrics.get('used_margin', 0.0), |
| 21701 | read_only | 'margin_utilization': self._margin_metrics.get('margin_utilization', 0.0), |
| 21702 | read_only | 'total_margin_balance': self._margin_metrics.get('total_margin_balance', 10000.0), |
| 21703 | read_only | 'max_withdraw': self._margin_metrics.get('max_withdraw', 10000.0) |
| 21720 | read_only | 'available_margin': self._margin_metrics.get('available_balance', 10000.0), |
| 21721 | read_only | 'used_margin': self._margin_metrics.get('used_margin', 0.0), |
| 21722 | read_only | 'margin_utilization': self._margin_metrics.get('margin_utilization', 0.0), |
| 21723 | read_only | 'total_margin_balance': self._margin_metrics.get('total_margin_balance', 10000.0), |
| 21724 | read_only | 'max_withdraw': self._margin_metrics.get('max_withdraw', 10000.0) |
| 21727 | read_only | self._real_balance = float(account_info.get('totalWalletBalance', 0)) if account_info else self._real_balance |
| 21730 | read_only | total_margin_balance = float(account_info.get('totalMarginBalance', 0)) if account_info else self._margin_metrics.get('total_margin_balance', 0) |
| 21731 | read_only | available_balance = float(account_info.get('availableBalance', 0)) if account_info else self._margin_metrics.get('available_balance', 0) |
| 21732 | read_only | total_position_margin = float(account_info.get('totalPositionInitialMargin', 0)) if account_info else self._margin_metrics.get('total_position_margin', 0) |
| 21733 | read_only | total_open_order_margin = float(account_info.get('totalOpenOrderInitialMargin', 0)) if account_info else self._margin_metrics.get('total_open_order_margin', 0) |
| 21734 | read_only | total_maint_margin = float(account_info.get('totalMaintMargin', 0)) if account_info else self._margin_metrics.get('total_maint_margin', 0) |
| 21735 | read_only | max_withdraw_amount = float(account_info.get('maxWithdrawAmount', 0)) if account_info else self._margin_metrics.get('max_withdraw', 0) |
| 21757 | read_only | sym = acc_pos.get('symbol', '') |
| 21758 | read_only | lev = acc_pos.get('leverage') |
| 21785 | read_only | symbol = pos.get('symbol') or pos.get('s') |
| 21786 | read_only | position_amt = float(pos.get('positionAmt', 0)) |
| 21790 | read_only | entry_price = float(pos.get('entryPrice', 0)) |
| 21791 | read_only | mark_price = float(pos.get('markPrice') or pos.get('mp') or entry_price) |
| 21792 | read_only | unrealized_pnl = float(pos.get('unRealizedProfit') or pos.get('up') or 0) |
| 21794 | read_only | position_margin = float(pos.get('initialMargin') or pos.get('isolatedMargin') or 0) |
| 21799 | read_only | # does NOT return leverage field. Fallback to pos.get('leverage') for websocket data. |
| 21800 | read_only | symbol_leverage = leverage_map.get(symbol, int(pos.get('leverage') or pos.get('l') or 1)) |
| 21812 | read_only | 'margin_type': (pos.get('marginType') or pos.get('mt') or 'cross'), |
| 21814 | read_only | 'liquidation_price': float(pos.get('liquidationPrice', 0)) |
| 21916 | read_only | trader_positions: dict, redis_client) -> None: |
| 21918 | read_only | size = float(pos_dict.get('size', 0)) |
| 21925 | read_only | mark_price = float(pos_dict.get('current_price') or pos_dict.get('entry_price') or 0) |
| 21929 | read_only | open_time = pos_dict.get('open_time') or pos_dict.get('timestamp') |
| 21940 | read_only | 'entry_price': float(pos_dict.get('entry_price', 0)), |
| 21942 | read_only | 'unrealized_pnl': float(pos_dict.get('unrealized_pnl', 0)), |
| 21943 | read_only | 'pnl_percentage': float(pos_dict.get('pnl_pct', 0)), |
| 21945 | read_only | 'leverage': int(pos_dict.get('leverage', 1)), |
| 21946 | read_only | 'liquidation_price': float(pos_dict.get('liquidation_price', 0)), |
| 21947 | read_only | 'buffer_percent': float(pos_dict.get('buffer_percent', 0)), |
| 21948 | read_only | 'stop_loss': float(pos_dict.get('stop_loss', 0)), |
| 21949 | read_only | 'take_profit': float(pos_dict.get('take_profit', 0)), |
| 21954 | read_only | 'last_update': pos_dict.get('timestamp') |
| 21961 | read_only | """Sync trading positions from Redis from all accounts using account-specific keys""" |
| 21965 | read_only | # Use the trainer's Redis client directly |
| 21966 | read_only | redis_client = None |
| 21967 | read_only | if hasattr(self.config, 'redis_client') and self.config.redis_client: |
| 21968 | read_only | redis_client = self.config.redis_client |
| 21969 | read_only | elif hasattr(self, 'redis') and self.redis: |
| 21970 | read_only | redis_client = self.redis |
| 21973 | read_only | import redis |
| 21974 | read_only | redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True) |
| 21976 | read_only | if redis_client: |
| 21979 | read_only | # PERF: Avoid Redis SCAN over full keyspace on every call (very slow). |
| 21980 | read_only | # We know the active accounts and symbols; fetch deterministically via pipelined HGETALL. |
| 21989 | read_only | # Cache results briefly to avoid repeated Redis work within the same second. |
| 21997 | read_only | pipe = redis_client.pipeline() |
| 21999 | read_only | pipe.hgetall(k) |
| 22013 | read_only | has_long = position_hash.get("has_long", "false") |
| 22014 | read_only | has_short = position_hash.get("has_short", "false") |
| 22026 | read_only | if float(pos_dict.get("size", 0) or 0) > 0: |
| 22027 | read_only | self._add_trader_position(account_id, symbol, "LONG", pos_dict, trader_positions, redis_client) |
| 22034 | read_only | if float(pos_dict.get("size", 0) or 0) > 0: |
| 22035 | read_only | self._add_trader_position(account_id, symbol, "SHORT", pos_dict, trader_positions, redis_client) |
| 22052 | read_only | position_data = redis_client.hgetall(position_key) |
| 22054 | read_only | if position_data and (position_data.get('has_long') == 'True' or position_data.get('has_short') == 'True'): |
| 22059 | read_only | if position_data.get('has_long') == 'True' and 'long' in position_data: |
| 22062 | read_only | if long_data.get('size', 0) > 0: |
| 22066 | read_only | current_price = long_data.get('current_price') |
| 22067 | read_only | entry_price = long_data.get('entry_price') |
| 22072 | read_only | open_time = long_data.get('open_time') |
| 22080 | read_only | 'size': float(long_data.get('size') or 0), |
| 22081 | read_only | 'entry_price': float(long_data.get('entry_price') or 0), |
| 22083 | read_only | 'unrealized_pnl': float(long_data.get('unrealized_pnl') or 0), |
| 22084 | read_only | 'pnl_percentage': float(long_data.get('pnl_pct') or 0), |
| 22085 | read_only | 'notional': float(long_data.get('size') or 0) * mark_price, |
| 22086 | read_only | 'leverage': int(long_data.get('leverage') or 1), |
| 22087 | read_only | 'liquidation_price': float(long_data.get('liquidation_price') or 0), |
| 22088 | read_only | 'buffer_percent': float(long_data.get('buffer_percent') or 0), |
| 22089 | read_only | 'stop_loss': float(long_data.get('stop_loss') or 0), |
| 22090 | read_only | 'take_profit': float(long_data.get('take_profit') or 0), |
| 22095 | read_only | 'last_update': position_data.get('last_update') |
| 22098 | read_only | logger.debug(f"Added LONG position: {symbol} {long_data.get('size')} @ {mark_price}") |
| 22103 | read_only | if position_data.get('has_short') == 'True' and 'short' in position_data: |
| 22106 | read_only | if short_data.get('size', 0) > 0: |
| 22110 | read_only | current_price = short_data.get('current_price') |
| 22111 | read_only | entry_price = short_data.get('entry_price') |
| 22116 | read_only | open_time = short_data.get('open_time') |
| 22124 | read_only | 'size': float(short_data.get('size') or 0), |
| 22125 | read_only | 'entry_price': float(short_data.get('entry_price') or 0), |
| 22127 | read_only | 'unrealized_pnl': float(short_data.get('unrealized_pnl') or 0), |
| 22128 | read_only | 'pnl_percentage': float(short_data.get('pnl_pct') or 0), |
| 22129 | read_only | 'notional': float(short_data.get('size') or 0) * mark_price, |
| 22130 | read_only | 'leverage': int(short_data.get('leverage') or 1), |
| 22131 | read_only | 'liquidation_price': float(short_data.get('liquidation_price') or 0), |
| 22132 | read_only | 'buffer_percent': float(short_data.get('buffer_percent') or 0), |
| 22133 | read_only | 'stop_loss': float(short_data.get('stop_loss') or 0), |
| 22134 | read_only | 'take_profit': float(short_data.get('take_profit') or 0), |
| 22139 | read_only | 'last_update': position_data.get('last_update') |
| 22142 | read_only | logger.debug(f"Added SHORT position: {symbol} {short_data.get('size')} @ {mark_price}") |
| 22154 | read_only | acc = pos.get('account_id', pos.get('source', 'unknown')) |
| 22197 | read_only | prev = cur.get(symbol) |
| 22198 | read_only | if prev is None or int(priority) >= int(prev.get("priority", -1)): |
| 22204 | write_risk_state | def _why_no_open_risk_mark_published(self, symbol: str): |
| 22209 | write_risk_state | self._why_no_open_risk_cycle_published_open_risk.add(str(symbol)) |
| 22215 | write_metric | flats = set() |
| 22218 | write_metric | has_pos = set() |
| 22221 | read_only | sym = str(p.get("symbol") or "").strip() |
| 22222 | read_only | sz = float(p.get("size", 0) or 0) |
| 22232 | write_metric | return set() |
| 22243 | write_risk_state | published = getattr(self, "_why_no_open_risk_cycle_published_open_risk", None) or set() |
| 22251 | write_metric | for sym in sorted(set(blocks.keys()) & set(flat)): |
| 22252 | write_metric | if sym in published: |
| 22254 | read_only | rec = blocks.get(sym) or {} |
| 22255 | read_only | gate = str(rec.get("gate") or "").strip() |
| 22256 | read_only | detail = str(rec.get("detail") or "").strip() |
| 22259 | read_only | last = getattr(self, "_why_no_open_risk_last", {}).get(sym) |
| 22266 | write_metric | from utils.ensemble_diagnostics import publish_ensemble_diagnostic |
| 22268 | write_metric | publish_ensemble_diagnostic( |
| 22316 | write_signal | # Signals published to signals:trading go to ALL accounts. |
| 22321 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 22327 | read_only | raw_eq = rc.get(f"portfolio:equity:{acct_id}") |
| 22333 | read_only | eq_usd = float(eq_data.get("equity_usd", 0.0) or 0.0) |
| 22334 | read_only | used_usd = float(eq_data.get("used_margin_usd", 0.0) or 0.0) |
| 22369 | read_only | pos_account = pos.get('account_id', 'primary') |
| 22376 | write_metric | seen_positions = set() |
| 22396 | write_metric | # Traders publish `portfolio:equity:{account_id}` with: |
| 22405 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 22407 | read_only | raw_eq = rc.get(f"portfolio:equity:{account_id}") |
| 22413 | read_only | eq_usd = float(eq.get("equity_usd", 0.0) or 0.0) |
| 22414 | read_only | avail_usd = float(eq.get("available_margin_usd", 0.0) or 0.0) |
| 22415 | read_only | used_usd = float(eq.get("used_margin_usd", 0.0) or 0.0) |
| 22417 | write_metric | # Reconcile partial snapshots (some publishers may omit one field) |
| 22430 | read_only | available_margin = portfolio.get('available_margin', 0) |
| 22431 | read_only | margin_utilization = portfolio.get('margin_utilization', 0) |
| 22432 | read_only | position_count = portfolio.get('position_count', 0) |
| 22433 | read_only | balance = portfolio.get('balance', 0) |
| 22455 | write_metric | # The trainer publishes to ALL accounts, so we use the MAX of per-account counts |
| 22465 | read_only | pos_account = pos.get('account_id', 'primary') |
| 22466 | read_only | per_account_counts[pos_account] = per_account_counts.get(pos_account, 0) + 1 |
| 22543 | read_only | projected_used_margin = portfolio.get('used_margin', 0) + required_margin |
| 22544 | read_only | total_margin = portfolio.get('total_margin_balance', balance) |
| 22590 | read_only | if (not allow_existing_position) and existing_position and existing_position.get('side') == side: |
| 22647 | read_only | # Get Redis client - HybridTrainer uses self.redis, GPUForcedPPO uses self._signal_redis |
| 22648 | read_only | redis_client = getattr(self, 'redis', None) or getattr(self, '_signal_redis', None) |
| 22649 | read_only | if not redis_client and hasattr(self, 'config'): |
| 22650 | read_only | redis_client = getattr(self.config, 'redis_client', None) |
| 22651 | read_only | if not redis_client: |
| 22654 | read_only | from utils.redis_client import get_redis |
| 22655 | read_only | redis_client = get_redis() |
| 22659 | read_only | if not redis_client: |
| 22683 | read_only | ws_connected_raw = redis_client.get('metrics:coinapi:ws:connected') |
| 22689 | read_only | msnap_data = redis_client.hgetall(msnap_key) |
| 22697 | read_only | present_fields = sum(1 for f in required_fields if f in msnap_data and msnap_data.get(f, '0') != '0') |
| 22701 | read_only | updated_ts_ms = float(msnap_data.get('updated_ts_ms', 0) or 0) |
| 22709 | read_only | spoof_score = float(msnap_data.get('spoof_score', 0) or 0) |
| 22710 | read_only | fast_move_score = float(msnap_data.get('fast_move_score', 0) or 0) |
| 22711 | read_only | fast_move_max_1m = float(msnap_data.get('fast_move_max_1m', 0) or 0) |
| 22712 | read_only | fast_move_max_5m = float(msnap_data.get('fast_move_max_5m', 0) or 0) |
| 22713 | read_only | snapback_score = float(msnap_data.get('snapback_score', 0) or 0) |
| 22714 | read_only | imbalance_5 = float(msnap_data.get('imbalance_5', 0) or 0) |
| 22715 | read_only | churn_score = float(msnap_data.get('churn_score', 0) or 0) |
| 22716 | read_only | spread_pct = float(msnap_data.get('spread', 0) or 0) * 100  # Convert to percent |
| 22717 | read_only | mid_px = float(msnap_data.get('mid_px', 0) or 0) |
| 22742 | read_only | microfeat_data = redis_client.hgetall(microfeat_key) |
| 22748 | read_only | microfeat_ts = float(microfeat_data.get('ts_ms', 0) or 0) |
| 22752 | read_only | ret_5s = float(microfeat_data.get('ret_5s', 0) or 0) |
| 22753 | read_only | ret_15s = float(microfeat_data.get('ret_15s', 0) or 0) |
| 22754 | read_only | ret_30s = float(microfeat_data.get('ret_30s', 0) or 0) |
| 22755 | read_only | ret_60s = float(microfeat_data.get('ret_60s', 0) or 0) |
| 22756 | read_only | accel_5s = float(microfeat_data.get('accel_5s', 0) or 0) |
| 22757 | read_only | accel_15s = float(microfeat_data.get('accel_15s', 0) or 0) |
| 22758 | read_only | volatility_30s = float(microfeat_data.get('volatility_30s', 0) or 0) |
| 22759 | read_only | volatility_60s = float(microfeat_data.get('volatility_60s', 0) or 0) |
| 22760 | read_only | is_squeeze_coinapi = microfeat_data.get('is_squeeze', '0') == '1' |
| 22761 | read_only | squeeze_magnitude = float(microfeat_data.get('squeeze_magnitude', 0) or 0) |
| 22762 | read_only | squeeze_direction_coinapi = int(float(microfeat_data.get('squeeze_direction', 0) or 0)) |
| 22779 | read_only | if use_rt_returns and redis_client: |
| 22780 | read_only | rt_raw = redis_client.get(f"price:realtime:{symbol}") |
| 22788 | read_only | rt_price = float(rt.get("price", 0.0) or 0.0) |
| 22789 | read_only | rt_ts_ms = int(rt.get("received_ts_ms") or rt.get("ts_ms") or 0) |
| 22796 | read_only | hist = self._rt_price_history.get(symbol) |
| 22798 | read_only | hist = deque(maxlen=800)  # ~80s at 10Hz; enough for 60s ret + jitter |
| 22931 | read_only | liq_analysis = self._analyze_liquidation_levels(symbol, mid_px if mid_px > 0 else 0, redis_client) |
| 22941 | read_only | ta_data = redis_client.hgetall(ta_key) if redis_client else {} |
| 22946 | read_only | ta_atr_14 = float(ta_data.get('ta_ATR_14_5m', 0) or 0) |
| 22947 | read_only | ta_rsi_14 = float(ta_data.get('ta_RSI_14_5m', 50) or 50) |
| 22948 | read_only | ta_adx_14 = float(ta_data.get('ta_ADX_14_5m', 25) or 25) |
| 22949 | read_only | ta_volume_obv = float(ta_data.get('ta_OBV_5m', 0) or 0) |
| 22959 | read_only | liq_analysis.get('near_liq_cluster', False)  # Near liquidation levels |
| 23081 | read_only | 'liq_cluster_distance_pct': liq_analysis.get('cluster_distance_pct', 0), |
| 23082 | read_only | 'liq_cluster_size_usd': liq_analysis.get('cluster_size_usd', 0), |
| 23083 | read_only | 'near_liq_cluster': liq_analysis.get('near_liq_cluster', False), |
| 23084 | read_only | 'liq_cascade_risk': liq_analysis.get('cascade_risk', 0), |
| 23271 | read_only | def _analyze_liquidation_levels(self, symbol: str, current_price: float, redis_client) -> Dict[str, Any]: |
| 23274 | read_only | Reads liquidation data from Redis (populated by live_binance_liquidations.py) |
| 23280 | read_only | redis_client: Redis connection |
| 23295 | read_only | if not redis_client or current_price <= 0: |
| 23298 | read_only | # Get recent liquidation data from Redis |
| 23301 | read_only | liq_data = redis_client.hgetall(liq_stats_key) |
| 23305 | read_only | coinank_data = redis_client.get(coinank_key) |
| 23318 | read_only | liq_price = float(liq_info.get('price', 0)) |
| 23319 | read_only | liq_qty = float(liq_info.get('quantity', 0)) |
| 23320 | read_only | liq_side = liq_info.get('side', '') |
| 23338 | read_only | liq_long = float(ck_data.get('liq_long_usd', 0)) |
| 23339 | read_only | liq_short = float(ck_data.get('liq_short_usd', 0)) |
| 23395 | read_only | 3. Redis keys (last resort) |
| 23410 | read_only | # PRIORITY 3: Redis keys (last resort) |
| 23411 | read_only | if hasattr(self.config, 'redis_client') and self.config.redis_client: |
| 23412 | read_only | redis_client = self.config.redis_client |
| 23414 | read_only | # Try multiple Redis key formats (in order of preference) |
| 23417 | read_only | rt_data = redis_client.get(rt_key) |
| 23428 | read_only | latest_price = redis_client.get(price_key) |
| 23434 | read_only | price = redis_client.get(simple_key) |
| 23440 | read_only | market_data = redis_client.get(market_key) |
| 23470 | read_only | aid = str((pos or {}).get("account_id") or "").strip().lower() |
| 23475 | read_only | if (pos or {}).get("symbol") != symbol: |
| 23477 | read_only | side = str(pos.get("side") or "").upper() |
| 23480 | read_only | size = float(pos.get("size", 0) or 0) |
| 23485 | read_only | pos["source"] = pos.get("account_id") or "trader" |
| 23504 | read_only | side = str(v.get("side") or "").upper() |
| 23507 | read_only | size = float(v.get("size", 0) or 0) |
| 23521 | read_only | n = float(p.get("notional", 0) or 0) |
| 23524 | read_only | sz = float(p.get("size", 0) or 0) |
| 23525 | read_only | px = float(p.get("mark_price", 0) or p.get("current_price", 0) or p.get("entry_price", 0) or 0) |
| 23553 | read_only | # Extract volatility from various field names (Redis hash has varied naming) |
| 23555 | read_only | safe_float(unified_features.get('ccxt_volatility_5m')) or |
| 23556 | read_only | safe_float(unified_features.get('ind_ta_volatility_5m')) or |
| 23557 | read_only | safe_float(unified_features.get('volatility_5m')) or |
| 23558 | read_only | safe_float(unified_features.get('volatility')) |
| 23561 | read_only | safe_float(unified_features.get('ccxt_volatility_1m')) or |
| 23562 | read_only | safe_float(unified_features.get('ind_ta_volatility_1m')) or |
| 23566 | read_only | safe_float(unified_features.get('ccxt_volatility_1h')) or |
| 23567 | read_only | safe_float(unified_features.get('ind_ta_volatility_1h')) or |
| 23573 | read_only | safe_float(unified_features.get('ccxt_price_change_5m')) or |
| 23574 | read_only | safe_float(unified_features.get('price_change_5m')) or |
| 23575 | read_only | safe_float(unified_features.get('momentum_5m')) or |
| 23576 | read_only | safe_float(unified_features.get('momentum')) |
| 23579 | read_only | safe_float(unified_features.get('ccxt_price_change_1m')) or |
| 23580 | read_only | safe_float(unified_features.get('price_change_1m')) or |
| 23586 | read_only | safe_float(unified_features.get('volume_ratio')) or |
| 23587 | read_only | safe_float(unified_features.get('ccxt_volume')) or |
| 23588 | read_only | safe_float(unified_features.get('volume')) |
| 23593 | read_only | safe_float(unified_features.get('ccxt_funding_rate')) or |
| 23594 | read_only | safe_float(unified_features.get('funding_rate')) or |
| 23595 | read_only | safe_float(unified_features.get('coinank_fundingRate_indicator_data_0_fundingRate')) or |
| 23596 | read_only | safe_float(unified_features.get('coinank_fundingRate_indicator_data_0_fr')) or |
| 23597 | read_only | safe_float(unified_features.get('coinank_fundingRate_kline_data_0_close')) or |
| 23598 | read_only | safe_float(unified_features.get('coinank_fundingRate_kline_data_0_open')) or |
| 23599 | read_only | safe_float(unified_features.get('coinank_funding_rate')) |
| 23603 | read_only | stress_level = safe_float(unified_features.get('stress_level')) or safe_float(unified_features.get('market_stress')) |
| 23623 | read_only | safe_float(unified_features.get('open_interest_change', 0.0)) or |
| 23626 | read_only | (safe_float(unified_features.get('coinank_openInterest_kline_data_0_close'), 0.0) - |
| 23627 | read_only | safe_float(unified_features.get('coinank_openInterest_kline_data_0_open'), 0.0)) |
| 23628 | read_only | / (safe_float(unified_features.get('coinank_openInterest_kline_data_0_open'), 0.0) or 1.0) |
| 23630 | read_only | if (safe_float(unified_features.get('coinank_openInterest_kline_data_0_open'), 0.0) or 0) > 0 |
| 23642 | read_only | if hasattr(self.config, 'redis_client') and self.config.redis_client: |
| 23643 | read_only | redis_client = self.config.redis_client |
| 23648 | read_only | price_data = redis_client.lrange(price_key, 0, 59)  # Last 60 data points |
| 23668 | read_only | volume_data = redis_client.get(volume_key) |
| 23669 | read_only | funding_data = redis_client.get(funding_key) |
| 23670 | read_only | oi_data = redis_client.get(oi_key) |
| 23703 | read_only | fallback_reasons = ["redis_client_missing"] |
| 23745 | read_only | regime = market_state.get('market_regime', 'normal') |
| 23746 | read_only | volatility_1m = market_state.get('volatility_1m', 0.5) |
| 23747 | read_only | stress_level = market_state.get('stress_level', 0.3) |
| 23851 | read_only | volume_ratio = market_state.get('volume_ratio', 1.0) |
| 23852 | read_only | funding_rate = abs(market_state.get('funding_rate', 0)) |
| 23943 | read_only | Get live position from Redis for position-aware signal generation. |
| 23949 | read_only | ph = self.redis.hgetall(key) or {} |
| 23973 | read_only | p.get("account_id") |
| 23974 | read_only | or p.get("account") |
| 23975 | read_only | or p.get("target_account_id") |
| 23979 | read_only | if (now - self._tg_last_sent.get(key, 0)) < self._tg_cooldown_s: |
| 24030 | read_only | atr_pct = float((payload or {}).get("atr_pct") or 0.0) |
| 24033 | read_only | _rc_e = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 24038 | read_only | result = _compute_price_target( |
| 24052 | read_only | tf_ta = ctx.get("tf_ta") or {} |
| 24055 | read_only | trend = str((entry or {}).get("Trend") or "").lower() |
| 24061 | write_metric | out = sorted(set(out), key=lambda x: order.get(x, 999)) |
| 24068 | read_only | p.get("current_price") |
| 24069 | read_only | or p.get("price") |
| 24070 | read_only | or ctx.get("price") |
| 24082 | read_only | equity = portfolio.get("total_balance") or portfolio.get("available_balance") or 100.0 |
| 24083 | read_only | available_balance = portfolio.get("available_balance", equity) |
| 24090 | read_only | # Prefer real-time computed measures from Redis-backed context. |
| 24092 | read_only | vol_ratio = float(ctx.get("volatility_ratio") or 0.0) |
| 24096 | read_only | stress_level = float(ctx.get("stress_level") or 0.0) |
| 24100 | read_only | "overall_regime": regime_analysis.get("overall", "normal"), |
| 24103 | read_only | "volatility": vol_ratio if vol_ratio > 0 else regime_analysis.get("volatility", 0.0), |
| 24104 | read_only | "stress_level": stress_level if stress_level > 0 else regime_analysis.get("stress_level", 0.0), |
| 24105 | read_only | "timeframe_regimes": regime_analysis.get("timeframe_regimes", {}), |
| 24110 | read_only | market_regime_info["structural_regime"] = structural.get("structural_regime") |
| 24111 | read_only | market_regime_info["macro_regime"] = structural.get("macro_regime") |
| 24112 | read_only | market_regime_info["effective_structural"] = structural.get("effective_regime") |
| 24113 | read_only | market_regime_info["structural_time_in_state_days"] = structural.get("time_in_state_days") |
| 24114 | read_only | market_regime_info["structural_metrics"] = structural.get("metrics") |
| 24115 | read_only | market_regime_info["risk_mode"] = structural.get("risk_mode") |
| 24120 | read_only | market_regime_info["regime_direction"] = axes.get("direction") |
| 24121 | read_only | market_regime_info["regime_structure"] = axes.get("structure") |
| 24122 | read_only | market_regime_info["regime_stress"] = axes.get("stress") |
| 24123 | read_only | market_regime_info["regime_scores"] = axes.get("scores") |
| 24124 | read_only | market_regime_info["regime_label"] = axes.get("label") |
| 24125 | read_only | market_regime_info["regime_health"] = axes.get("health") |
| 24128 | read_only | market_volatility = market_regime_info.get("volatility", 0.5) |
| 24147 | read_only | "price_target": p.get("price_target"), |
| 24148 | read_only | "price_target_pct": p.get("price_target_pct"), |
| 24149 | read_only | "price_target_direction": p.get("price_target_direction"), |
| 24150 | read_only | "price_target_basis": p.get("price_target_basis"), |
| 24152 | read_only | "action_type": p.get("action_type") or ("close" if "CLOSE" in str(action_name).upper() else "open"), |
| 24153 | read_only | "action_category": p.get("action_category") or p.get("category"), |
| 24154 | read_only | "reason": p.get("reason") or p.get("why") or p.get("source_reason"), |
| 24155 | read_only | "source": p.get("source") or "Hybrid PPO+MASA Trainer", |
| 24156 | read_only | "profit_intent": bool(p.get("profit_intent")) if "profit_intent" in p else None, |
| 24157 | read_only | "reversal_confirmed": bool(p.get("reversal_confirmed")) if "reversal_confirmed" in p else None, |
| 24158 | read_only | "close_fraction": p.get("close_fraction") if "close_fraction" in p else None, |
| 24159 | read_only | "close_pct": p.get("close_pct") if "close_pct" in p else None, |
| 24160 | read_only | "ride_move_active": bool(p.get("_ride_move_active")) if "_ride_move_active" in p else None, |
| 24161 | read_only | "ride_move_reason": p.get("_ride_move_reason") if "_ride_move_reason" in p else None, |
| 24162 | read_only | # Live position snapshot (from trader-written Redis) so exits make sense. |
| 24163 | read_only | "position": ctx.get("position"), |
| 24169 | read_only | "structural_regime": (market_regime_info or {}).get("effective_structural") or (market_regime_info or {}).get("structural_regime"), |
| 24170 | read_only | "macro_regime": (market_regime_info or {}).get("macro_regime"), |
| 24171 | read_only | "structural_time_in_state_days": (market_regime_info or {}).get("structural_time_in_state_days"), |
| 24172 | read_only | "structural_metrics": (market_regime_info or {}).get("structural_metrics"), |
| 24173 | read_only | "risk_mode": (market_regime_info or {}).get("risk_mode"), |
| 24174 | read_only | "regime_direction": (market_regime_info or {}).get("regime_direction"), |
| 24175 | read_only | "regime_structure": (market_regime_info or {}).get("regime_structure"), |
| 24176 | read_only | "regime_stress": (market_regime_info or {}).get("regime_stress"), |
| 24177 | read_only | "regime_scores": (market_regime_info or {}).get("regime_scores"), |
| 24178 | read_only | "regime_label": (market_regime_info or {}).get("regime_label"), |
| 24179 | read_only | "regime_health": (market_regime_info or {}).get("regime_health"), |
| 24189 | read_only | target_dir = (signal_data.get("price_target_direction") or "").upper() or None |
| 24192 | read_only | if signal_data.get("price_target") in (None, "") and target_dir: |
| 24193 | read_only | computed = _compute_price_target_local(float(signal_data.get("current_price") or 0.0), timeframe, confidence, target_dir) |
| 24201 | read_only | td = (signal_data.get("price_target_direction") or "").upper() or _infer_target_dir(action_name) |
| 24224 | read_only | Pulls real-time context from Redis for rich [REDACTED] alerts. |
| 24227 | read_only | r = self.redis |
| 24263 | read_only | v = m.get(key, None) |
| 24273 | read_only | v = r.get(px_key) |
| 24281 | read_only | p = j.get("price") or j.get("mark_price") or j.get("last") |
| 24294 | read_only | row = _decode_map(r.hgetall(f"unified_features:{symbol}:{timeframe}") or {}) |
| 24297 | read_only | row = _decode_map(r.hgetall(f"features:unified:{symbol}:{timeframe}") or {}) |
| 24319 | read_only | feat = _decode_map(r.hgetall(f"unified_features:{symbol}:{vol_tf}") or {}) |
| 24321 | read_only | feat = _decode_map(r.hgetall(f"unified_features:{symbol}:{timeframe}") or {}) |
| 24323 | read_only | feat = _decode_map(r.hgetall(f"features:unified:{symbol}:{vol_tf}") or {}) |
| 24363 | read_only | ema50 = float(d.get(b"ema_50", 0)) |
| 24364 | read_only | ema200 = float(d.get(b"ema_200", 0)) |
| 24365 | read_only | adx = float(d.get(b"adx_14", 0)) |
| 24375 | read_only | d = _decode_map(r.hgetall(f"unified_features:{symbol}:{timeframe}") or {}) |
| 24377 | read_only | d = _decode_map(r.hgetall(f"features:unified:{symbol}:{timeframe}") or {}) |
| 24381 | read_only | b"ema_50": d.get("ema_50") or d.get("ind_ta_ema_50") or 0, |
| 24382 | read_only | b"ema_200": d.get("ema_200") or d.get("ind_ta_ema_200") or 0, |
| 24383 | read_only | b"adx_14": d.get("adx_14") or d.get("ind_ta_adx") or 0, |
| 24392 | read_only | d = _decode_map(r.hgetall(f"unified_features:{symbol}:{tf}") or {}) |
| 24394 | read_only | d = _decode_map(r.hgetall(f"features:unified:{symbol}:{tf}") or {}) |
| 24404 | read_only | b"ema_50": d.get("ema_50") or d.get("ind_ta_ema_50") or 0, |
| 24405 | read_only | b"ema_200": d.get("ema_200") or d.get("ind_ta_ema_200") or 0, |
| 24406 | read_only | b"adx_14": d.get("adx_14") or d.get("ind_ta_adx") or 0, |
| 24470 | read_only | pos = ctx.get("position") or {} |
| 24472 | read_only | side = pos.get("side") or pos.get("positionSide") or "—" |
| 24473 | read_only | size = pos.get("size") or pos.get("positionAmt") or "0" |
| 24474 | read_only | levp = pos.get("leverage") or "—" |
| 24487 | read_only | margin_check = ctx.get("margin_check") or {} |
| 24490 | read_only | if margin_check.get('can_trade'): |
| 24491 | read_only | available = margin_check.get('available_margin', 0) |
| 24492 | read_only | required = margin_check.get('required_margin', 0) |
| 24493 | read_only | utilization = margin_check.get('margin_utilization', 0) |
| 24494 | read_only | projected = margin_check.get('projected_utilization', 0) |
| 24497 | read_only | reason = margin_check.get('reason', 'Unknown') |
| 24498 | read_only | available = margin_check.get('available_margin', 0) |
| 24499 | read_only | required = margin_check.get('required_margin', 0) |
| 24500 | read_only | utilization = margin_check.get('margin_utilization', 0) |
| 24501 | read_only | pos_count = margin_check.get('position_count', 0) |
| 24502 | read_only | max_pos = margin_check.get('max_positions', 10) |
| 24507 | read_only | margin_blocked = ctx.get("margin_blocked", False) |
| 24628 | read_only | regime_analysis['structural_regime'] = structural.get('effective_regime') |
| 24629 | read_only | regime_analysis['macro_regime'] = structural.get('macro_regime') |
| 24630 | read_only | regime_analysis['structural_metrics'] = structural.get('metrics') |
| 24631 | read_only | regime_analysis['structural_time_in_state_days'] = structural.get('time_in_state_days') |
| 24632 | read_only | regime_analysis['structural_risk_mode'] = structural.get('risk_mode') |
| 24668 | write_metric | self._missing_unified_warned = set() |
| 24670 | read_only | msg = f"⚠️ No unified features for {symbol} {timeframe} (expected Redis key unified_features:{symbol}:{timeframe}:latest); falling back to simple regime" |
| 24686 | read_only | if isinstance(regime_sequence, dict) and not regime_sequence.get("lstm_warmup_ready", True): |
| 24770 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 24779 | read_only | data = rc.hgetall(k) |
| 24789 | read_only | if k in data and data.get(k) not in (None, ""): |
| 24790 | read_only | return float(data.get(k)) |
| 24807 | read_only | if k in data and data.get(k) not in (None, ""): |
| 24808 | read_only | ts_ms = int(float(data.get(k))) |
| 24818 | read_only | def _update_structural_series(self, symbol: str, timeframe: str, close: float, ts_ms: int, maxlen: int) -> None: |
| 24819 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 24824 | read_only | last_ts_raw = rc.get(last_ts_key) |
| 24829 | write_metric | pipe.set(last_ts_key, str(ts_ms), ex=86400 * 7) |
| 24830 | write_metric | pipe.lpush(f"regime:structural:{symbol}:{timeframe}:closes", float(close)) |
| 24831 | read_only | pipe.ltrim(f"regime:structural:{symbol}:{timeframe}:closes", 0, maxlen - 1) |
| 24832 | write_metric | pipe.lpush(f"regime:structural:{symbol}:{timeframe}:ts", int(ts_ms)) |
| 24833 | read_only | pipe.ltrim(f"regime:structural:{symbol}:{timeframe}:ts", 0, maxlen - 1) |
| 24838 | read_only | def _get_structural_series(self, symbol: str, timeframe: str, maxlen: int) -> Tuple[List[float], List[int]]: |
| 24839 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 24843 | read_only | closes = rc.lrange(f"regime:structural:{symbol}:{timeframe}:closes", 0, maxlen - 1) |
| 24844 | read_only | tss = rc.lrange(f"regime:structural:{symbol}:{timeframe}:ts", 0, maxlen - 1) |
| 24861 | read_only | return int(order.get(str(regime or "NORMAL").upper(), 0)) |
| 24870 | read_only | self._update_structural_series(symbol, "1h", close_1h, ts_1h, maxlen=300) |
| 24872 | read_only | self._update_structural_series(symbol, "4h", close_4h, ts_4h, maxlen=120) |
| 24874 | read_only | self._update_structural_series(symbol, "1d", close_1d, ts_1d, maxlen=20) |
| 24966 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 24986 | read_only | state = rc.hgetall(state_key) or {} |
| 24990 | read_only | reclaim_active = str(state.get("reclaim_active", "0")) == "1" |
| 24991 | read_only | reclaim_ts = int(float(state.get("reclaim_ts", 0) or 0)) |
| 24992 | read_only | reclaim_px = float(state.get("reclaim_px", 0) or 0) |
| 24993 | read_only | low_since = float(state.get("low_since", cur_close) or cur_close) |
| 25024 | write_metric | rc.zadd(fail_zset, {str(now_ms): now_ms}) |
| 25041 | write_metric | rc.hset( |
| 25090 | read_only | dd_5d = metrics.get("dd_5d", 0.0) |
| 25091 | read_only | dd_10d = metrics.get("dd_10d", 0.0) |
| 25092 | read_only | trend_state = metrics.get("trend_state", "NEUTRAL") |
| 25093 | read_only | rf_10d = int(metrics.get("rf_10d", 0) or 0) |
| 25094 | read_only | close_1d = metrics.get("close_1d") |
| 25095 | read_only | vwap_1d = metrics.get("vwap_1d") |
| 25096 | read_only | atr_1d = metrics.get("atr_1d") |
| 25097 | read_only | vr = metrics.get("vol_ratio", 0.0) |
| 25098 | read_only | rv_10d = metrics.get("rv_10d", 0.0) |
| 25104 | read_only | r_last = metrics.get("rv_24h", 0.0) / max(rv_10d, 1e-9) |
| 25128 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 25135 | read_only | st = rc.hgetall(state_key) or {} |
| 25136 | read_only | prev_state = str(st.get("state") or "NORMAL").upper() |
| 25137 | read_only | entered_ts = int(float(st.get("entered_ts", entered_ts))) |
| 25138 | read_only | recovery_streak = int(float(st.get("recovery_streak", 0) or 0)) |
| 25169 | read_only | min_hold = int(hold_sec.get(prev_state, 0)) |
| 25178 | write_metric | rc.hset( |
| 25204 | read_only | prev = float(self._regime_ema_cache.get(key, value)) |
| 25317 | read_only | vol_ratio = float(structural_metrics.get("vol_ratio", 0.0) or 0.0) |
| 25340 | read_only | last_gate = self._last_liquidity_gate_result.get(symbol, {}) if hasattr(self, "_last_liquidity_gate_result") else {} |
| 25341 | read_only | ob_ts = int(last_gate.get("orderbook_ts_ms") or 0) |
| 25366 | read_only | dd5 = float(structural_metrics.get("dd_5d", 0.0) or 0.0) |
| 25367 | read_only | dd10 = float(structural_metrics.get("dd_10d", 0.0) or 0.0) |
| 25403 | read_only | direction = str(axes.get("direction") or "NEUTRAL").upper() |
| 25404 | read_only | structure = str(axes.get("structure") or "RANGE").upper() |
| 25405 | read_only | stress = str(axes.get("stress") or "LOW").upper() |
| 25437 | read_only | direction = str(axes.get("direction") or "NEUTRAL").upper() |
| 25438 | read_only | structure = str(axes.get("structure") or "RANGE").upper() |
| 25439 | read_only | stress = str(axes.get("stress") or "LOW").upper() |
| 25463 | read_only | sym_regime = str(sym_state.get("state") or "NORMAL").upper() |
| 25464 | read_only | macro_regime = str(macro_state.get("state") or "NORMAL").upper() |
| 25481 | read_only | "time_in_state_days": sym_state.get("time_in_state_days", 0.0), |
| 25482 | read_only | "metrics": sym_state.get("metrics", {}), |
| 25510 | read_only | score = regime_scores.get(regime, 4)  # Default to normal |
| 25553 | read_only | 'overall_regime': regime_analysis.get('overall', 'normal'), |
| 25560 | read_only | regime_report['timeframes'][tf] = regime_analysis.get(tf, 'normal') |
| 25569 | read_only | tf_summary = " / ".join([f"{tf}:{regime_analysis.get(tf, 'N')[:4]}" for tf in timeframes]) |
| 25572 | read_only | # Store in Redis for signal access (if Redis is available) |
| 25573 | read_only | if self._signal_redis is not None: |
| 25574 | read_only | redis_key = f"regime_analysis:{symbol}:latest" |
| 25575 | read_only | self._signal_redis.setex(redis_key, 300, json.dumps(regime_report))  # 5min expiry |
| 25587 | read_only | regimes = [regime_analysis.get(tf) for tf in timeframes if tf in regime_analysis] |
| 25733 | read_only | if current_position and current_position.get('side') and current_position.get('pnl_pct'): |
| 25760 | read_only | logger.debug(f"   Current Position PnL: {profit_taking_status.get('current_profit', 0.0):.2f}%") |
| 25761 | read_only | logger.debug(f"   Recommended Action: {profit_taking_status.get('recommended_action', 'none')}") |
| 25798 | read_only | Uses Redis hashes (canonical and :latest) instead of stringified JSON. |
| 25801 | read_only | redis_client = self._signal_redis |
| 25824 | read_only | data = redis_client.hgetall(key) |
| 25834 | read_only | data = redis_client.hgetall(key) |
| 25870 | read_only | _safe_float(features.get('returns_1m', features.get('return_1m', 0.0))), |
| 25871 | read_only | _safe_float(features.get('returns_5m', features.get('return_5m', 0.0))), |
| 25872 | read_only | _safe_float(features.get('atr', features.get('atr14', 0.0))), |
| 25873 | read_only | _safe_float(features.get('adx', features.get('adx14', 0.0))), |
| 25874 | read_only | _safe_float(features.get('volatility', features.get('volatility_trend_short', 0.0))), |
| 25875 | read_only | _safe_float(features.get('funding_rate', 0.0)), |
| 25876 | read_only | _safe_float(features.get('open_interest_change', features.get('oi_change', 0.0))), |
| 25877 | read_only | _safe_float(features.get('volume_trend_5m', 0.0)), |
| 25907 | read_only | trend_persistence = lstm_features.get('trend_persistence', 0.5) |
| 25910 | read_only | volatility_stability = lstm_features.get('volatility_stability', 0.5) |
| 25913 | read_only | momentum_regime = lstm_features.get('momentum_regime', 0.0) |
| 25916 | read_only | regime_change_prob = lstm_features.get('regime_change_probability', 0.1) |
| 25919 | read_only | temporal_confidence = lstm_features.get('temporal_confidence', 0.5) |
| 26036 | read_only | momentum = self._safe_float(features.get('price_momentum_long', features.get('price_momentum_short', 0.0)), 0.0) |
| 26037 | read_only | adx = self._safe_float(features.get('adx', features.get('adx14', 0.0)), 0.0) |
| 26038 | read_only | atr = self._safe_float(features.get('atr', features.get('atr14', 0.0)), 0.0) |
| 26039 | read_only | volatility = abs(self._safe_float(features.get('volatility', features.get('volatility_trend_short', 0.0)), 0.0)) |
| 26077 | read_only | vix = self._safe_float(features.get('vix_index', 20), 20.0) |
| 26081 | read_only | liquidations = self._safe_float(features.get('liquidations_24h', 0), 0.0) |
| 26082 | read_only | liq_threshold = self._safe_float(features.get('liquidations_avg_7d', liquidations), liquidations) * 3 |
| 26087 | read_only | funding_rate = abs(self._safe_float(features.get('funding_rate', 0), 0.0)) |
| 26091 | read_only | correlation = self._safe_float(features.get('btc_correlation', 0.7), 0.7) |
| 26095 | read_only | fear_greed = self._safe_float(features.get('fear_greed_index', 50), 50.0) |
| 26120 | read_only | rsi = self._safe_float(features.get('rsi_14', 50), 50.0) |
| 26128 | read_only | macd = self._safe_float(features.get('macd_signal', 0), 0.0) |
| 26151 | read_only | atr = self._safe_float(features.get('atr_14', 0), 0.0) |
| 26152 | read_only | price = self._safe_float(features.get('current_price', 1), 1.0) |
| 26158 | read_only | realized_vol = self._safe_float(features.get('volatility_24h', 0), 0.0) |
| 26162 | read_only | bb_width = self._safe_float(features.get('bb_width', 0), 0.0) |
| 26180 | read_only | bid_ask_spread = self._safe_float(features.get('bid_ask_spread', 0), 0.0) |
| 26181 | read_only | order_book_depth = self._safe_float(features.get('order_book_depth', 1000000), 1000000.0) |
| 26184 | read_only | volume_24h = self._safe_float(features.get('volume_24h', 0), 0.0) |
| 26185 | read_only | volume_avg = self._safe_float(features.get('volume_avg_7d', volume_24h), float(volume_24h) if volume_24h else 1.0) |
| 26210 | read_only | fear_greed = self._safe_float(features.get('fear_greed_index', 50), 50.0) |
| 26214 | read_only | social_sentiment = self._safe_float(features.get('social_sentiment', 0.5), 0.5) |
| 26218 | read_only | funding_rate = self._safe_float(features.get('funding_rate', 0), 0.0) |
| 26225 | read_only | long_short_ratio = self._safe_float(features.get('long_short_ratio', 1.0), 1.0) |
| 26249 | read_only | btc_correlation = self._safe_float(features.get('btc_correlation', 0.7), 0.7) |
| 26252 | read_only | spy_correlation = self._safe_float(features.get('spy_correlation', 0.3), 0.3) |
| 26255 | read_only | dxy_correlation = self._safe_float(features.get('dxy_correlation', -0.2), -0.2) |
| 26258 | read_only | gold_correlation = self._safe_float(features.get('gold_correlation', 0.1), 0.1) |
| 26293 | read_only | # Helper to safely get float from features (Redis returns strings) |
| 26295 | read_only | val = features.get(key, default) |
| 26496 | read_only | watch_data = self._reversal_watch.get(symbol, {}) |
| 26497 | read_only | peak_roi = watch_data.get('peak_roi', 0.0) |
| 26640 | read_only | pred_data = self._signal_redis.hgetall(pred_key) if hasattr(self, '_signal_redis') else {} |
| 26643 | read_only | action = pred_data.get('action', '').decode() if isinstance(pred_data.get('action'), bytes) else pred_data.get('action', '') |
| 26644 | read_only | conf = float(pred_data.get('confidence', 0)) |
| 26711 | read_only | htf = tf_preds.get("1h", {}) |
| 26712 | read_only | vhtf = tf_preds.get("4h", {}) |
| 26713 | read_only | ltf_5 = tf_preds.get("5m", {}) |
| 26714 | read_only | ltf_15 = tf_preds.get("15m", {}) |
| 26718 | read_only | if not pred or not pred.get("dir"): |
| 26734 | read_only | float((p or {}).get("conf", 0.0) or 0.0) > 0.0 |
| 26757 | read_only | "htf_conf": float(htf.get("conf", 0.0)) if htf else 0.0, |
| 26758 | read_only | "vhtf_conf": float(vhtf.get("conf", 0.0)) if vhtf else 0.0, |
| 26760 | read_only | "5m": float(ltf_5.get("conf", 0.0)) if ltf_5 else 0.0, |
| 26761 | read_only | "15m": float(ltf_15.get("conf", 0.0)) if ltf_15 else 0.0, |
| 26867 | read_only | max_conf = tf_summary.get("max_conf", 0.0) |
| 26903 | read_only | Data source: Redis hash `prediction:{symbol}:{timeframe}` (non-blocking best-effort). |
| 26908 | read_only | r = getattr(self, "_signal_redis", None) |
| 26912 | read_only | raw = r.hgetall(key) or {} |
| 26916 | read_only | def _get(k: str): |
| 26917 | read_only | v = raw.get(k) or raw.get(k.encode()) |
| 26922 | read_only | action = _get("action") or "" |
| 26924 | read_only | conf = float(_get("confidence") or 0.0) |
| 26939 | read_only | # Check cache first to avoid Redis calls during training |
| 26944 | read_only | cached = self._prediction_cache.get(cache_key) |
| 26953 | read_only | # CRITICAL: Add timeout and non-blocking Redis access |
| 26954 | read_only | if hasattr(self, '_signal_redis') and self._signal_redis: |
| 26957 | read_only | pred_data = self._signal_redis.hgetall(pred_key) |
| 26958 | read_only | except (redis.exceptions.TimeoutError, redis.exceptions.ConnectionError): |
| 26959 | read_only | # Use safe defaults on Redis timeout - don't block training |
| 26964 | read_only | # Redis returns bytes->bytes; support both string and bytes keys. |
| 26965 | read_only | def _get(k: str): |
| 26966 | read_only | v = pred_data.get(k) |
| 26968 | read_only | v = pred_data.get(k.encode()) |
| 26974 | read_only | _get("action") |
| 26975 | read_only | or _get("action_name") |
| 26976 | read_only | or _get("predicted_action") |
| 26981 | read_only | conf = float(_get("confidence") or _get("model_confidence") or 0.0) |
| 26987 | read_only | _pt = _get("price_target") |
| 26992 | read_only | _ptp = _get("price_target_pct") |
| 26997 | read_only | _ptd = _get("price_target_direction") |
| 27047 | read_only | (p.get("dir") in ("FLAT", None, "") and float(p.get("conf", 0.0)) <= 0.0) |
| 27054 | read_only | _warn_last = self._tf_flat_warn_ts.get(symbol, 0.0) |
| 27085 | read_only | # CRITICAL: Non-blocking Redis access with timeout |
| 27086 | read_only | if not hasattr(self, '_signal_redis') or not self._signal_redis: |
| 27091 | read_only | feature_data = self._signal_redis.hgetall(feature_key) |
| 27092 | read_only | except (redis.exceptions.TimeoutError, redis.exceptions.ConnectionError): |
| 27093 | read_only | logger.debug(f"Redis timeout for regime detection {symbol}:{timeframe}") |
| 27102 | read_only | atr_normalized = float(feature_data.get('atr_14', b'0.5').decode() if isinstance(feature_data.get('atr_14'), bytes) else feature_data.get('atr_14', 0.5)) |
| 27103 | read_only | volume_ratio = float(feature_data.get('volume_ratio_ma20', b'1.0').decode() if isinstance(feature_data.get('volume_ratio_ma20'), bytes) else feature_data.get('volume_ratio_ma20', 1.0)) |
| 27106 | read_only | ema_50 = float(feature_data.get('ema_50', b'0.0').decode() if isinstance(feature_data.get('ema_50'), bytes) else feature_data.get('ema_50', 0.0)) |
| 27107 | read_only | ema_200 = float(feature_data.get('ema_200', b'0.0').decode() if isinstance(feature_data.get('ema_200'), bytes) else feature_data.get('ema_200', 0.0)) |
| 27108 | read_only | rsi_14 = float(feature_data.get('rsi_14', b'50.0').decode() if isinstance(feature_data.get('rsi_14'), bytes) else feature_data.get('rsi_14', 50.0)) |
| 27114 | read_only | price_data = self._signal_redis.hget(price_key, 'price') |
| 27199 | read_only | features = self._signal_redis.hgetall(feature_key) if hasattr(self, '_signal_redis') else {} |
| 27203 | read_only | liq_long = float(features.get('liquidation_long_level', 0)) |
| 27204 | read_only | liq_short = float(features.get('liquidation_short_level', 0)) |
| 27205 | read_only | liq_volume = float(features.get('liquidation_volume', 0)) |
| 27304 | read_only | # Get S/R data from TokenMetrics via Redis |
| 27306 | read_only | sr_data = self._signal_redis.hgetall(tm_key) if hasattr(self, '_signal_redis') else {} |
| 27310 | read_only | supports_str = sr_data.get('support_levels', b'').decode() if isinstance(sr_data.get('support_levels'), bytes) else sr_data.get('support_levels', '') |
| 27333 | read_only | resistances_str = sr_data.get('resistance_levels', b'').decode() if isinstance(sr_data.get('resistance_levels'), bytes) else sr_data.get('resistance_levels', '') |
| 27396 | read_only | default_cfg = ranges.get("default") or {"min_leverage": 10, "max_leverage": 25} |
| 27397 | read_only | leverage_config = ranges.get(symbol, default_cfg) or default_cfg |
| 27405 | read_only | market_state = market_analysis.get('market_state', {}) or {} |
| 27408 | read_only | market_state.get('volatility_1m') |
| 27409 | read_only | or market_state.get('volatility_5m') |
| 27410 | read_only | or market_state.get('volatility', 0) |
| 27425 | read_only | liq_analysis = market_analysis.get('liquidation_analysis', {}) |
| 27426 | read_only | sr_analysis = market_analysis.get('sr_analysis', {}) |
| 27429 | read_only | if sr_analysis.get('at_support'): |
| 27436 | read_only | result['reason'] = f"At support level - prioritizing LONG (${sr_analysis.get('nearest_support', 0):.4f})" |
| 27438 | read_only | elif sr_analysis.get('at_resistance'): |
| 27445 | read_only | result['reason'] = f"At resistance level - prioritizing SHORT (${sr_analysis.get('nearest_resistance', 0):.4f})" |
| 27447 | read_only | elif liq_analysis.get('action_recommendation') == 'LONG_LIQUIDATION_SWEEP_EXPECTED': |
| 27454 | read_only | result['reason'] = f"LONG liquidation sweep expected - {liq_analysis.get('reason', '')}" |
| 27456 | read_only | elif liq_analysis.get('action_recommendation') == 'SHORT_LIQUIDATION_SWEEP_EXPECTED': |
| 27463 | read_only | result['reason'] = f"SHORT liquidation sweep expected - {liq_analysis.get('reason', '')}" |
| 27498 | read_only | default_cfg = ranges.get("default") or {"min_leverage": 10, "max_leverage": 25} |
| 27499 | read_only | leverage_config = ranges.get(symbol, default_cfg) or default_cfg |
| 27502 | read_only | base_leverage = (int(leverage_config.get("min_leverage", 10)) + int(leverage_config.get("max_leverage", 25))) // 2 |
| 27542 | write_signal | or str(action_name or '').upper() in set(hedge_actions) |
| 27555 | read_only | current_side = position.get('side', 'NONE') |
| 27556 | read_only | position_pnl_pct = float(position.get('pnl_pct', 0.0) or 0.0) |
| 27580 | read_only | cooldown = self._signal_cooldown_seconds.get(timeframe, 300)  # Default 5 min |
| 27589 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 27592 | read_only | raw = rc.get(f"portfolio:equity:{aid}") |
| 27595 | read_only | eq = float((j or {}).get("equity_usd", 0.0) or 0.0) |
| 27596 | read_only | av = float((j or {}).get("available_margin_usd", 0.0) or 0.0) |
| 27608 | read_only | last_signal = self._last_signal_data.get(signal_key) |
| 27637 | read_only | remaining = max(1e-9, 1.0 - float(last_signal.get('confidence', 0.0) or 0.0)) |
| 27643 | read_only | if current_price and last_signal.get('price'): |
| 27695 | read_only | # This makes the problem visible in Redis for audits without relying on manual log scraping. |
| 27699 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 27714 | write_metric | rc.xadd("health:events", {"data": json.dumps(evt)}, maxlen=2000, approximate=True) |
| 27872 | write_metric | (published by traders into Redis and surfaced via `_get_current_position`). |
| 27880 | read_only | dist_cached = position.get('liquidation_distance_pct', None) |
| 27888 | read_only | float(position.get('current_price') or 0) |
| 27889 | read_only | or float(position.get('mark_price') or 0) |
| 27890 | read_only | or float(position.get('entry_price') or 0) |
| 27892 | read_only | side = str(position.get('side', 'LONG')).upper() |
| 27893 | read_only | liquidation_price = float(position.get('liquidation_price') or position.get('liquidationPrice') or 0) |
| 27906 | read_only | if hasattr(self, 'config') and hasattr(self.config, 'redis_client') and self.config.redis_client: |
| 27908 | read_only | price_data = self.config.redis_client.lrange(price_key, 0, 4)  # Last 5 prices |
| 27929 | read_only | current_price = position.get('mark_price', position.get('entry_price', 0)) |
| 27930 | read_only | side = position.get('side', 'LONG') |
| 27941 | read_only | highest_pnl_pct = position.get('highest_pnl_pct', current_pnl_pct) |
| 27992 | read_only | side = position.get('side', 'LONG') |
| 27993 | read_only | position_duration_hours = position.get('duration_hours', 0) |
| 28007 | read_only | regime = market_state.get('market_regime', 'normal') |
| 28038 | read_only | _regime_analysis = market_state.get('regime_analysis') or {} |
| 28042 | read_only | _htf_regime = str(_regime_analysis.get(_htf, '')).lower() |
| 28062 | read_only | _hedge_loss_pct = float(_hpos.get('pnl_pct', 0) or _hpos.get('unrealized_pnl_pct', 0) or 0) |
| 28070 | read_only | _hp = _accts.get(_hk) |
| 28072 | read_only | _hedge_loss_pct = float(_hp.get('pnl_pct', 0) or _hp.get('unrealized_pnl_pct', 0) or _hp.get('roi_pct', 0) or 0) |
| 28080 | read_only | _last_loss_close_ts = getattr(self, '_last_breakout_loss_close_ts', {}).get(symbol, 0) |
| 28107 | read_only | {tf: str(_regime_analysis.get(tf, 'unknown')) for tf in BREAKOUT_LOSS_ACCEPT_HTF_CONFIRM_TFS}, |
| 28210 | read_only | side = position.get('side', 'LONG').upper() |
| 28211 | read_only | pnl_pct = float(position.get('pnl_percentage', 0) or position.get('pnl_pct', 0) or 0) |
| 28229 | read_only | positions_data = self._signal_redis.hgetall("positions:wajid-futures-usdt") or {} |
| 28245 | read_only | current_entry_ts = float(self._signal_redis.hget(current_entry_key, "entry_time") or 0) |
| 28246 | read_only | opposite_entry_ts = float(self._signal_redis.hget(opposite_entry_key, "entry_time") or 0) |
| 28253 | read_only | opposite_pnl = float(opposite_pos.get('pnl_percentage', 0) or 0) |
| 28295 | read_only | spoof_score = micro.get('spoof_score', 0) |
| 28296 | read_only | fast_move_score = micro.get('fast_move_score', 0) |
| 28297 | read_only | imbalance = micro.get('imbalance_5', 0)  # Order book imbalance |
| 28298 | read_only | spread = micro.get('spread', 0) |
| 28368 | read_only | new_conf = float(new_signal.get('model_confidence', 0) or new_signal.get('confidence', 0) or 0) |
| 28369 | read_only | new_symbol = new_signal.get('symbol') |
| 28379 | read_only | if micro.get('spoof_score', 0) < 0.3 and micro.get('fast_move_score', 0) < 0.3: |
| 28380 | read_only | if micro.get('book_bid_sum_5', 0) > 0 and micro.get('book_ask_sum_5', 0) > 0: |
| 28394 | read_only | pos_symbol = pos_data.get('symbol', pos_key.split('_')[0]) |
| 28395 | read_only | pos_conf = float(pos_data.get('entry_confidence', 0) or pos_data.get('confidence', 0) or 0.5) |
| 28396 | read_only | pos_pnl = float(pos_data.get('pnl_pct', 0) or pos_data.get('pnl_percentage', 0) or 0) |
| 28397 | read_only | pos_side = pos_data.get('side', 'LONG') |
| 28398 | read_only | pos_margin = float(pos_data.get('margin_used', 0) or pos_data.get('initialMargin', 0) or 0) |
| 28474 | read_only | position_side = position.get('side', 'LONG') |
| 28475 | read_only | pnl_pct = abs(position.get('pnl_percentage', 0) or 0) |
| 28482 | read_only | htf_bias = tf_summary.get('htf_bias', 0)  # 1h |
| 28483 | read_only | vhtf_bias = tf_summary.get('vhtf_bias', 0)  # 4h |
| 28484 | read_only | ltf_bias = tf_summary.get('ltf_bias', 0)  # 5m+15m |
| 28510 | read_only | volume_ratio = float(features.get('volume_ratio', 1.0)) |
| 28566 | read_only | current_side = current_pos.get('side', 'LONG') |
| 28569 | read_only | # Get position metadata from Redis (entry_time, etc.) |
| 28572 | read_only | raw_ts = self._signal_redis.hget(metadata_key, "entry_time") |
| 28582 | read_only | if dynamic_monitor_suggestion and dynamic_monitor_suggestion.get('action') not in ['NO_ACTION', 'HOLD']: |
| 28583 | read_only | monitor_action = dynamic_monitor_suggestion.get('action') |
| 28587 | read_only | f"Dynamic monitor suggests {monitor_action} - {dynamic_monitor_suggestion.get('reason', 'N/A')}" |
| 28592 | read_only | close_fraction = dynamic_monitor_suggestion.get('close_fraction', 0.5) |
| 28595 | read_only | 'reason': dynamic_monitor_suggestion.get('reason', 'Rebalancing position'), |
| 28616 | read_only | htf_bias = tf_summary.get('htf_bias', 0) |
| 28617 | read_only | htf_conf = tf_summary.get('htf_conf', 0.0) |
| 28672 | read_only | f"Microstructure quick profit triggered - {micro_decision.get('reason', 'N/A')}" |
| 28685 | read_only | entry_price = float(current_pos.get('entry_price', 0) or 0) |
| 28686 | read_only | current_price = float(current_pos.get('current_price', 0) or current_pos.get('mark_price', 0) or 0) |
| 28687 | read_only | roi_pct = float(current_pos.get('roi_pct', 0) or current_pnl_pct) |
| 28694 | read_only | trail_state = self._adaptive_trail_state.get(position_id, {}) |
| 28695 | read_only | peak_roi = trail_state.get('peak_roi', 0) |
| 28696 | read_only | trail_activation_roi = trail_state.get('activation_roi', 0) |
| 28734 | read_only | trail_distance = trail_state.get('trail_distance_pct', 0.5) |
| 28735 | read_only | peak = trail_state.get('peak_roi', roi_pct) |
| 28944 | read_only | if not microstructure.get('analysis_available', False): |
| 28947 | read_only | staleness_ms = microstructure.get('msnap_staleness_ms', 999999) |
| 28956 | read_only | imbalance = float(microstructure.get('imbalance_5', 0) or 0) |
| 28959 | read_only | liq_analysis = microstructure.get('liquidation_analysis', {}) |
| 28960 | read_only | near_long_liq = liq_analysis.get('long_liq_distance_pct', 100) < 1.0  # Within 1% |
| 28961 | read_only | near_short_liq = liq_analysis.get('short_liq_distance_pct', 100) < 1.0 |
| 28962 | read_only | long_liq_value = float(liq_analysis.get('long_liq_value_usd', 0) or 0) |
| 28963 | read_only | short_liq_value = float(liq_analysis.get('short_liq_value_usd', 0) or 0) |
| 28966 | read_only | is_squeeze = microstructure.get('is_squeeze', False) |
| 28967 | read_only | squeeze_direction = microstructure.get('squeeze_direction')  # 'long', 'short', or None |
| 28968 | read_only | squeeze_severity = float(microstructure.get('squeeze_severity', 0) or 0) |
| 28971 | read_only | accel = float(microstructure.get('momentum_acceleration', 0) or 0) |
| 28972 | read_only | ret_5s = float(microstructure.get('ret_5s', 0) or 0) |
| 28973 | read_only | ret_15s = float(microstructure.get('ret_15s', 0) or 0) |
| 28974 | read_only | ret_60s = float(microstructure.get('ret_60s', 0) or 0) |
| 28977 | read_only | spoof_score = float(microstructure.get('spoof_score', 0) or 0) |
| 28978 | read_only | churn_score = float(microstructure.get('churn_score', 0) or 0) |
| 28979 | read_only | snapback_score = float(microstructure.get('snapback_score', 0) or 0) |
| 28982 | read_only | fast_move_score = float(microstructure.get('fast_move_score', 0) or 0) |
| 28983 | read_only | fast_move_max_1m = float(microstructure.get('fast_move_max_1m', 0) or 0) |
| 29163 | read_only | # Try to get cached confidence from Redis or recent predictions |
| 29165 | read_only | cached_conf = self._signal_redis.get(key) |
| 29290 | read_only | tf_mult = tf_multipliers.get(timeframe, 1.0) |
| 29439 | read_only | if isinstance(tf_summary, dict) and tf_summary.get("account_id"): |
| 29440 | read_only | account_id = str(tf_summary.get("account_id")).strip().lower() |
| 29443 | read_only | equity_usd = float(self._margin_metrics.get('total_wallet_balance', 10000.0) or 10000.0) |
| 29444 | read_only | free_margin_usd = float(self._margin_metrics.get('available_balance', equity_usd) or equity_usd) |
| 29445 | read_only | used_margin_usd = float(self._margin_metrics.get('used_margin', 0) or 0) |
| 29502 | read_only | if isinstance(tf_summary, dict) and tf_summary.get("account_id"): |
| 29503 | read_only | acct_target = str(tf_summary.get("account_id")).strip().lower() |
| 29518 | read_only | st.get("margin_utilization_pct", st.get("margin_utilization", st.get("margin_ratio", 0.0))) |
| 29547 | read_only | st.get("margin_utilization_pct", st.get("margin_utilization", st.get("margin_ratio", 0.0))) |
| 29556 | read_only | current_margin_util = float(util_by_acct.get(best_acct, 0.0) or 0.0) |
| 29562 | read_only | current_margin_util = float(self._margin_metrics.get('margin_utilization', 0) or 0.0) |
| 29564 | read_only | current_margin_util = float(self._margin_metrics.get('margin_utilization', 0) or 0.0) |
| 29603 | read_only | if isinstance(tf_summary, dict) and tf_summary.get("account_id"): |
| 29604 | read_only | acct_target = str(tf_summary.get("account_id")).strip().lower() |
| 29614 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 29618 | read_only | raw = rc.get(f"portfolio:equity:{aid}") if rc is not None else None |
| 29633 | read_only | wallet = float(eqd.get("wallet_balance_usd") or 0.0) |
| 29634 | read_only | used = float(eqd.get("used_margin_usd") or eqd.get("initial_margin_usd") or 0.0) |
| 29635 | read_only | avail = float(eqd.get("available_margin_usd") or eqd.get("available_balance_usd") or 0.0) |
| 29647 | read_only | w = float(eqd.get("wallet_balance_usd") or 0.0) |
| 29648 | read_only | u = float(eqd.get("used_margin_usd") or eqd.get("initial_margin_usd") or 0.0) |
| 29649 | read_only | a = float(eqd.get("available_margin_usd") or eqd.get("available_balance_usd") or 0.0) |
| 29716 | write_signal | self._signal_redis.xadd( |
| 29719 | read_only | maxlen=5000, |
| 29723 | write_signal | logger.debug(f"Failed to publish rebalance signal: {e}") |
| 29777 | read_only | side = pos.get('side', 'UNKNOWN') |
| 29778 | read_only | source = pos.get('source', 'unknown') |
| 29781 | read_only | size = pos.get('size', 0) |
| 29797 | read_only | 'available_margin': self._margin_metrics.get('available_balance', 10000.0), |
| 29798 | read_only | 'used_margin': self._margin_metrics.get('used_margin', 0.0), |
| 29799 | read_only | 'margin_utilization': self._margin_metrics.get('margin_utilization', 0.0), |
| 29800 | read_only | 'total_margin_balance': self._margin_metrics.get('total_margin_balance', 10000.0), |
| 29801 | read_only | 'max_withdraw': self._margin_metrics.get('max_withdraw', 10000.0) |
| 29836 | read_only | if liquidation_analysis.get('near_liquidation_zone'): |
| 29838 | read_only | 'confidence': liquidation_analysis.get('confidence', 0.5), |
| 29841 | read_only | 'direction': liquidation_analysis.get('liquidation_direction'), |
| 29842 | read_only | 'action': liquidation_analysis.get('action_recommendation'), |
| 29858 | read_only | from utils.redis_client import get_redis_client |
| 29859 | read_only | get_redis_client().hincrby('trainer:critical_fixes:stats', 'liq_blocked', 1) |
| 29881 | read_only | if liquidation_analysis.get('near_liquidation_zone'): |
| 29882 | read_only | logger.info(f"🔥 LIQUIDATION ZONE: {symbol} - {liquidation_analysis.get('reason', 'near liquidation levels')}") |
| 29884 | read_only | if sr_analysis.get('at_support') or sr_analysis.get('at_resistance'): |
| 29885 | read_only | level_type = 'support' if sr_analysis.get('at_support') else 'resistance' |
| 29886 | read_only | level_price = sr_analysis.get(f'nearest_{level_type}', 0) |
| 29887 | read_only | logger.info(f"🎯 KEY LEVEL: {symbol} at {level_type.upper()} ${level_price:.4f} - {sr_analysis.get('reason', '')}") |
| 29894 | read_only | if microstructure.get('analysis_available'): |
| 29900 | read_only | 'scalp_score': microstructure.get('scalp_opportunity_score', 0), |
| 29901 | read_only | 'mm_score': microstructure.get('market_maker_score', 0), |
| 29902 | read_only | 'fake_breakout_risk': microstructure.get('fake_breakout_risk', 0), |
| 29903 | read_only | 'execution_urgency': microstructure.get('execution_urgency', 0), |
| 29904 | read_only | 'price_velocity': microstructure.get('price_velocity_1s', 0) |
| 29910 | read_only | f"urgency: {ultra_fast_signal.get('execution_urgency', 0)})") |
| 29933 | read_only | f"✅ [EXIT-DECISION] {symbol} {current_pos.get('side')}: " |
| 29934 | read_only | f"{exit_decision['action']} - {exit_decision.get('reason', 'N/A')}" |
| 29963 | read_only | masa_confidence_multiplier = min(1.0, masa_analysis.get('confidence_multiplier', 1.0))  # Cap at 1.0 — can only reduce |
| 29967 | read_only | if market_state.get('is_high_volatility', False): |
| 29970 | read_only | if market_state.get('is_extreme_volatility', False): |
| 29991 | read_only | if market_state.get('is_extreme_volatility', False): |
| 29996 | read_only | elif market_state.get('is_high_volatility', False): |
| 30016 | write_metric | # Get current portfolio state from Redis (trader publishes this) |
| 30020 | read_only | volatility = market_state.get('volatility_1m', 1.0) |
| 30024 | read_only | if rebalance_check.get('should_rebalance'): |
| 30030 | read_only | if margin_check.get('should_adjust'): |
| 30036 | read_only | fallback_equity = portfolio.get('available_balance', 0) or 57.0 |
| 30041 | read_only | per_account = portfolio.get('per_account', []) |
| 30044 | read_only | f"{a.get('account_id', '?').upper()}=${a.get('total_balance', 0):.0f}" |
| 30053 | read_only | active_acct = (portfolio.get('active_account') or 'unknown').upper() |
| 30114 | read_only | current_pnl = current_pos.get('unrealized_pnl', 0) |
| 30116 | read_only | position_duration = current_pos.get('duration_hours', 1)  # Default 1 hour if not available |
| 30117 | read_only | leverage = float(current_pos.get('leverage', 1) or 1) |
| 30128 | read_only | _rc_s = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 30141 | read_only | regime = market_state.get('market_regime', 'normal') |
| 30199 | write_metric | # Try to get account-specific fees from Redis (published by trader) |
| 30208 | read_only | cached_fee = self._margin_metrics.get('round_trip_fee_pct') |
| 30221 | read_only | funding_rate = abs(market_state.get('funding_rate', 0)) |
| 30349 | read_only | current_position_notional = abs(current_pos.get('size', 0) * current_pos.get('entry_price', 1)) |
| 30484 | read_only | if liquidation_analysis.get('near_liquidation_zone'): |
| 30485 | read_only | liq_direction = liquidation_analysis.get('liquidation_direction') |
| 30489 | read_only | if liquidation_analysis.get('action_recommendation') == 'SHORT_LIQUIDATION_SWEEP_EXPECTED': |
| 30496 | read_only | if liquidation_analysis.get('action_recommendation') == 'LONG_LIQUIDATION_SWEEP_EXPECTED': |
| 30502 | read_only | if sr_analysis.get('at_resistance') and current_side == 'LONG': |
| 30505 | read_only | result['reason'] = f'🎯 RESISTANCE PROFIT: +{current_pnl_pct:.1f}% on LONG at resistance ${sr_analysis.get("nearest_resistance", 0):.4f} - taking profits at key level' |
| 30508 | read_only | elif sr_analysis.get('at_support') and current_side == 'SHORT': |
| 30511 | read_only | result['reason'] = f'🎯 SUPPORT PROFIT: +{current_pnl_pct:.1f}% on SHORT at support ${sr_analysis.get("nearest_support", 0):.4f} - taking profits at key level' |
| 31193 | read_only | if not ppo_path_p.exists() and state_dict_path.exists(): |
| 31198 | read_only | if not ppo_path_p.exists() and str(ppo_path_p).endswith('.zip'): |
| 31200 | read_only | if alt_state_dict.exists(): |
| 31205 | read_only | if not ppo_path_p.exists(): |
| 31223 | read_only | if checkpoint_metadata.get('is_state_dict_checkpoint') or str(ppo_path_p).endswith('.state_dict.pt'): |
| 31227 | read_only | logger.info(f"✅ State dict loaded ({len(pending_state_dict.get('policy_state_dict', {}))} keys) - will apply to fresh model") |
| 31297 | write_signal | # Successfully loaded - attach signal publisher and MASA, then return |
| 31301 | write_signal | self.attach_signal_publisher(self.redis, min_conf=config.MIN_TRADING_CONFIDENCE) |
| 31303 | read_only | # Inject Redis into the loaded PPO model (SB3 load() skips __init__). |
| 31304 | read_only | if not getattr(self.ppo_model, '_signal_redis', None): |
| 31305 | read_only | self.ppo_model._signal_redis = self.redis |
| 31316 | read_only | masa_path = checkpoint_metadata.get("masa_checkpoint_path") or checkpoint_metadata.get("masa_path") |
| 31326 | read_only | if mp.exists(): |
| 31417 | read_only | rh_ts = checkpoint_metadata.get('timestamp', '') |
| 31441 | write_checkpoint_metadata | # Never delete checkpoints automatically (operator-owned artifacts). |
| 31465 | read_only | logger.info("   - Redis (live features for all symbols/timeframes)") |
| 31561 | read_only | if not getattr(self.ppo_model, '_signal_redis', None): |
| 31562 | read_only | self.ppo_model._signal_redis = self.redis |
| 31584 | read_only | if pending_state_dict.get('optimizer_state_dict') and hasattr(self.ppo_model.policy, 'optimizer'): |
| 31592 | read_only | if pending_state_dict.get('scaler_state_dict') and hasattr(self.ppo_model, 'scaler') and self.ppo_model.scaler is not None: |
| 31600 | read_only | save_fmt = pending_state_dict.get('save_format', 'legacy') |
| 31601 | read_only | ckpt_loops = pending_state_dict.get('loops', 0) |
| 31602 | read_only | ckpt_timesteps = pending_state_dict.get('timesteps', 0) |
| 31627 | write_signal | # TODO: after PPO model creation - attach signal publisher |
| 31630 | write_signal | self.attach_signal_publisher(self.redis, min_conf=config.MIN_TRADING_CONFIDENCE) |
| 31881 | read_only | f"entropy={entropy:.3f} most_common={action_names.get(most_common_action, most_common_action)} " |
| 31922 | read_only | _sz = abs(float(_pv.get('size', 0) or _pv.get('positionAmt', 0) or 0)) |
| 31939 | read_only | # Check 3: risk_off latch in Redis |
| 31941 | read_only | _rc = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 31945 | read_only | if _rc.exists(_rk): |
| 31973 | read_only | f"(3 consecutive on {action_names.get(most_common_action, most_common_action)}). " |
| 32006 | read_only | f"dominant={action_names.get(most_common_action, most_common_action)}" |
| 32209 | read_only | loops = int(checkpoint_metadata.get('loops', 0) or 0) |
| 32213 | read_only | total_timesteps = int(checkpoint_metadata.get('timesteps', 0) or 0) |
| 32217 | read_only | total_episodes = int(checkpoint_metadata.get('episodes', 0) or 0) |
| 32221 | read_only | best_reward = float(checkpoint_metadata.get('best_reward', float('-inf'))) |
| 32276 | write_signal | # Initialize env-index mapping for signal publishing (skip if already done) |
| 32446 | write_metric | if stop_event.is_set(): |
| 32531 | read_only | logger.info(f"📊 Pre-training GPU: {pre_memory.get('utilization_pct', 0):.1f}% VRAM, {pre_memory.get('fragmentation_mb', 0):.1f}MB fragmented") |
| 32542 | write_metric | self.training_active.set() |
| 32546 | write_metric | self.training_step_in_progress.set() |
| 32658 | read_only | logger.info(f"[ENTERPRISE-TRAIN] MoE: loss={moe_metrics.get('moe_total_loss', 0):.4f}") |
| 32666 | read_only | logger.info(f"[ENTERPRISE-TRAIN] Uncertainty: loss={unc_metrics.get('uncertainty_train_loss', 0):.4f}") |
| 32708 | write_metric | loop_stop_event.set() |
| 32730 | write_metric | loop_stop_event.set() |
| 32775 | write_metric | loop_stop_event.set() |
| 32779 | write_metric | if hasattr(self, 'training_step_in_progress') and self.training_step_in_progress.is_set(): |
| 32781 | write_metric | if hasattr(self, 'training_active') and self.training_active.is_set(): |
| 32790 | write_metric | loop_stop_event.set() |
| 32795 | read_only | logger.info(f"📊 Post-training GPU: {post_memory.get('utilization_pct', 0):.1f}% VRAM, status: {post_memory.get('status', 'unknown')}") |
| 32802 | write_heartbeat | # E.2) Status & Heartbeat Publishing (every loop) |
| 32806 | read_only | redis_client = self.redis |
| 32821 | read_only | redis_client.setex('status:trainer', 60, json.dumps(status_data))  # 60s TTL |
| 32824 | write_heartbeat | redis_client.set('heartbeat:Trainer', str(current_time_ms)) |
| 32827 | write_metric | self._publish_rl_metrics_to_redis( |
| 32880 | read_only | self.episode_rewards.append(ep.get('r', 0.0)) |
| 32885 | read_only | wins = sum(ep.get('wins', 0) for ep in loop_episode_stats) |
| 32886 | read_only | losses = sum(ep.get('losses', 0) for ep in loop_episode_stats) |
| 32887 | read_only | total_trades = sum(ep.get('trades', ep.get('trade_count', 0)) for ep in loop_episode_stats) |
| 32888 | read_only | total_profit = sum(ep.get('total_profit', max(ep.get('pnl', 0.0), 0.0)) for ep in loop_episode_stats) |
| 32889 | read_only | total_loss = sum(ep.get('total_loss', max(-ep.get('pnl', 0.0), 0.0)) for ep in loop_episode_stats) |
| 32891 | read_only | wins = sum(1 for ep in loop_episode_stats if ep.get('pnl', 0.0) > 0) |
| 32892 | read_only | losses = sum(1 for ep in loop_episode_stats if ep.get('pnl', 0.0) < 0) |
| 32893 | read_only | net_pnl = sum(ep.get('net_pnl', ep.get('pnl', 0.0)) for ep in loop_episode_stats) |
| 32894 | read_only | reward_sum = sum(ep.get('r', 0.0) for ep in loop_episode_stats) |
| 32896 | read_only | avg_len = sum(ep.get('l', 0) for ep in loop_episode_stats) / max(total_episodes_in_loop, 1) |
| 32897 | read_only | peak_drawdown = max((ep.get('max_drawdown', 0.0) for ep in loop_episode_stats), default=0.0) |
| 32898 | read_only | risk_adj_reward_avg = sum(ep.get('risk_adj_reward', 0.0) for ep in loop_episode_stats) / max(total_episodes_in_loop, 1) |
| 32899 | read_only | raw_reward_avg = sum(ep.get('raw_reward_total', 0.0) for ep in loop_episode_stats) / max(total_episodes_in_loop, 1) |
| 32900 | read_only | risk_reward_avg = sum(ep.get('risk_reward_total', 0.0) for ep in loop_episode_stats) / max(total_episodes_in_loop, 1) |
| 32927 | write_metric | # Publish loop summary diagnostics to Redis for dashboards |
| 32929 | read_only | redis_client = getattr(self, '_signal_redis', None) |
| 32930 | read_only | if redis_client: |
| 32931 | write_metric | redis_client.hset('rl:metrics:loop_summary', mapping={ |
| 32946 | read_only | redis_client.expire('rl:metrics:loop_summary', 3600) |
| 32948 | write_metric | logger.debug(f"Loop summary redis publish failed: {e}") |
| 33025 | read_only | recent_sharpe = perf_metrics.get('sharpe_ratio', 0) |
| 33072 | write_metric | # P0-3/P1-4: Publish RL metrics to Redis for dashboard visibility |
| 33078 | write_metric | self._publish_rl_metrics_to_redis( |
| 33110 | read_only | if portfolio.get('using_real_data'): |
| 33111 | read_only | accounts = portfolio.get('accounts', {}) |
| 33113 | read_only | primary_positions = accounts.get('primary', {}).get('positions', []) |
| 33114 | read_only | asjad_positions = accounts.get('asjad', {}).get('positions', []) |
| 33117 | read_only | primary_eq = accounts.get('primary', {}).get('equity', 0) |
| 33118 | read_only | asjad_eq = accounts.get('asjad', {}).get('equity', 0) |
| 33121 | read_only | f"COMBINED: ${portfolio.get('balance', 0):.2f} / " |
| 33122 | read_only | f"margin_util={portfolio.get('margin_utilization', 0):.1f}%") |
| 33156 | read_only | # CRITICAL FIX: Close Redis connections BEFORE vec_env cleanup |
| 33158 | read_only | # because Redis connections contain thread locks that can't be pickled |
| 33159 | read_only | if hasattr(self, '_signal_redis') and self._signal_redis is not None: |
| 33161 | read_only | self._signal_redis.close() |
| 33162 | read_only | self._signal_redis = None |
| 33163 | read_only | logger.debug("✅ Redis connection closed before vec_env cleanup") |
| 33164 | read_only | except Exception as redis_err: |
| 33165 | read_only | logger.debug(f"⚠️ Redis close error (non-fatal): {redis_err}") |
| 33167 | read_only | # Close vectorized environment (now safe - no Redis locks to pickle) |
| 33210 | write_metric | def _publish_rl_metrics_to_redis( |
| 33219 | write_metric | P0-3/P1-4: Publish RL training metrics to Redis for dashboard visibility. |
| 33221 | write_metric | Publishes to the following keys (required by dashboard): |
| 33229 | read_only | redis_client = self._signal_redis  # Use existing Redis connection |
| 33245 | read_only | value_loss = metrics.get('train/value_loss', 0.0) |
| 33246 | read_only | policy_loss = metrics.get('train/policy_gradient_loss', 0.0) |
| 33247 | read_only | entropy_loss = metrics.get('train/entropy_loss', 0.0) |
| 33248 | read_only | approx_kl = metrics.get('train/approx_kl', 0.0) |
| 33271 | write_metric | # Publish main training metrics |
| 33289 | write_metric | # Publish to rl:metrics:continuous (hash) |
| 33290 | write_metric | redis_client.hset('rl:metrics:continuous', mapping={ |
| 33295 | read_only | redis_client.expire('rl:metrics:continuous', 3600) |
| 33297 | write_metric | # Publish total episodes |
| 33298 | write_metric | redis_client.set('rl:episodes:total', str(total_episodes)) |
| 33300 | write_heartbeat | # Publish trainer heartbeat (milliseconds) |
| 33301 | write_heartbeat | redis_client.set('heartbeat:Trainer', str(current_time_ms)) |
| 33303 | write_metric | # Publish observation length |
| 33305 | write_metric | redis_client.set('rl:obs_length', str(obs_length)) |
| 33307 | write_metric | # Publish per-timeframe metrics (aggregate by timeframe) |
| 33315 | write_metric | redis_client.hset(f'rl:metrics:{tf}', mapping={ |
| 33318 | read_only | redis_client.expire(f'rl:metrics:{tf}', 3600) |
| 33320 | write_metric | logger.debug(f"📊 [RL-METRICS] Published loop #{loop_number} metrics to Redis") |
| 33323 | write_metric | logger.warning(f"⚠️ Failed to publish RL metrics to Redis: {e}") |
| 33350 | read_only | has_long = current_positions.get('long', {}).get('size', 0) > 0 |
| 33351 | read_only | has_short = current_positions.get('short', {}).get('size', 0) > 0 |
| 33353 | read_only | long_size = float(current_positions.get('long', {}).get('size', 0)) |
| 33354 | read_only | short_size = float(current_positions.get('short', {}).get('size', 0)) |
| 33356 | read_only | long_notional = float(current_positions.get('long', {}).get('notional', 0)) |
| 33357 | read_only | short_notional = float(current_positions.get('short', {}).get('notional', 0)) |
| 33466 | read_only | if portfolio.get('positions'): |
| 33467 | read_only | positions = portfolio.get('positions', []) |
| 33471 | read_only | elif portfolio.get('per_account'): |
| 33472 | read_only | for acc_data in portfolio.get('per_account', []): |
| 33473 | read_only | acc_positions = acc_data.get('positions', []) |
| 33475 | read_only | logger.debug(f"[HEDGE_STATUS_CHECK] Aggregated from {len(portfolio.get('per_account', []))} accounts") |
| 33481 | read_only | side = 'LONG' if float(pos_data.get('positionAmt', 0)) > 0 else 'SHORT' if float(pos_data.get('positionAmt', 0)) < 0 else None |
| 33486 | read_only | 'size': abs(float(pos_data.get('positionAmt', 0))), |
| 33487 | read_only | 'notional': abs(float(pos_data.get('notional', 0) or pos_data.get('positionAmt', 0) * float(pos_data.get('markPrice', 0)))), |
| 33488 | read_only | 'entryPrice': float(pos_data.get('entryPrice', 0)), |
| 33489 | read_only | 'unrealized_pnl': float(pos_data.get('unRealizedProfit', 0) or pos_data.get('unrealized_pnl', 0)) |
| 33493 | read_only | # Source 4: Try Redis position keys directly |
| 33496 | read_only | rc = self._signal_redis if self._signal_redis is not None else get_redis() |
| 33500 | read_only | pos_data = rc.hgetall(pos_key) |
| 33502 | read_only | side = pos_data.get(b'side', pos_data.get('side', b'')).decode() if isinstance(pos_data.get(b'side', pos_data.get('side', b'')), bytes) else pos_data.get('side', '') |
| 33503 | read_only | size = float(pos_data.get(b'size', pos_data.get('size', 0))) |
| 33504 | read_only | notional = float(pos_data.get(b'notional', pos_data.get('notional', 0))) |
| 33512 | read_only | logger.debug(f"[HEDGE_STATUS_CHECK] Using Redis position keys") |
| 33513 | read_only | except Exception as redis_err: |
| 33514 | read_only | logger.debug(f"[HEDGE_STATUS_CHECK] Redis fallback failed: {redis_err}") |
| 33521 | read_only | symbol = pos.get('symbol', '') |
| 33522 | read_only | side = pos.get('side', '').upper() |
| 33523 | read_only | size = pos.get('size', 0) or pos.get('positionAmt', 0) or 0 |
| 33524 | read_only | notional = pos.get('notional', 0) or 0 |
| 33544 | read_only | logger.debug(f"[HEDGE_STATUS_CHECK] {symbol} enforce result: action={hedge_status[symbol].get('action')} target_side={hedge_status[symbol].get('target_side')}") |
| 33565 | write_signal | list of hedge signals to be published |
| 33573 | read_only | action = status.get('action', 'UNKNOWN') |
| 33574 | read_only | logger.debug(f"[HEDGE_GEN] {symbol}: action={action} target_side={status.get('target_side')}") |
| 33585 | read_only | 'target_notional': status.get('target_notional', status.get('additional_notional', 0)), |
| 33624 | read_only | # Get recent price data from Redis if available |
| 33626 | read_only | if hasattr(self, '_signal_redis'): |
| 33627 | read_only | recent_data = self._signal_redis.hget(feature_key, "volatility_14") |
| 33693 | read_only | }.get(tf, 1.0) |
| 33775 | read_only | base_time = base_times.get(tf, "unknown") |
| 33799 | read_only | action_name = action_names.get(action, f"UNKNOWN_ACTION_{action}") |
| 33847 | read_only | return f"AI analysis suggests {action_names.get(action, 'UNKNOWN')} for {symbol} with {confidence:.2f} confidence." |
| 33904 | read_only | if not getattr(self, "_signal_redis", None): |
| 33910 | read_only | h = self._signal_redis.hgetall(f"unified_features:{symbol}:{tf}") |
| 33926 | read_only | funding = float(features.get('funding_rate') or 0.0) |
| 33937 | read_only | funding = float(features.get(k) or 0.0) |
| 33951 | read_only | oi_change = float(features.get('open_interest_change') or 0.0) |
| 33954 | read_only | oi_open = features.get("coinank_openInterest_kline_data_0_open") |
| 33955 | read_only | oi_close = features.get("coinank_openInterest_kline_data_0_close") |
| 33971 | read_only | ls_ratio = float(features.get('long_short_ratio') or 0.0) |
| 33980 | read_only | ls_ratio = float(features.get(k) or 0.0) |
| 34002 | read_only | features = self._signal_redis.hgetall(features_key) |
| 34049 | read_only | features = self._signal_redis.hgetall(features_key) |
| 34125 | read_only | # Get Redis feature data |
| 34127 | read_only | if hasattr(self, 'redis') and self.redis: |
| 34128 | read_only | feature_data = self.redis.hgetall(feature_key) |
| 34164 | read_only | feature_data.get('coinank_liquidations_long') |
| 34165 | read_only | or feature_data.get('coinank_liquidation_history_data_0_longTurnover') |
| 34169 | read_only | feature_data.get('coinank_liquidations_short') |
| 34170 | read_only | or feature_data.get('coinank_liquidation_history_data_0_shortTurnover') |
| 34184 | read_only | oi_change = float(feature_data.get('coinank_oi_change_pct') or feature_data.get('open_interest_change') or 0) |
| 34187 | read_only | oi_open = float(feature_data.get('coinank_openInterest_kline_data_0_open') or 0) |
| 34188 | read_only | oi_close = float(feature_data.get('coinank_openInterest_kline_data_0_close') or 0) |
| 34199 | read_only | feature_data.get('coinank_funding_rate') |
| 34200 | read_only | or feature_data.get('coinank_fundingRate_indicator_data_0_fundingRate') |
| 34201 | read_only | or feature_data.get('coinank_fundingRate_indicator_data_0_fr') |
| 34202 | read_only | or feature_data.get('coinank_fundingRate_kline_data_0_close') |
| 34203 | read_only | or feature_data.get('coinank_fundingRate_kline_data_0_open') |
| 34227 | read_only | rsi = float(feature_data.get('rsi_14', 50)) |
| 34238 | read_only | macd = float(feature_data.get('macd', 0)) |
| 34239 | read_only | macd_signal = float(feature_data.get('macd_signal', 0)) |
| 34246 | read_only | bb_position = float(feature_data.get('bb_position', 0.5)) |
| 34263 | read_only | volume_sma = float(feature_data.get('volume_sma_20', 0)) |
| 34264 | read_only | current_volume = float(feature_data.get('volume', 0)) |
| 34281 | read_only | # Get Redis data for comprehensive analysis |
| 34283 | read_only | if hasattr(self, 'redis') and self.redis: |
| 34284 | read_only | feature_data = self.redis.hgetall(feature_key) |
| 34320 | read_only | feature_data.get('coinank_liquidations_long') |
| 34321 | read_only | or feature_data.get('coinank_liquidation_history_data_0_longTurnover') |
| 34325 | read_only | feature_data.get('coinank_liquidations_short') |
| 34326 | read_only | or feature_data.get('coinank_liquidation_history_data_0_shortTurnover') |
| 34335 | read_only | oi_change = float(feature_data.get('coinank_oi_change_pct') or feature_data.get('open_interest_change') or 0) |
| 34338 | read_only | oi_open = float(feature_data.get('coinank_openInterest_kline_data_0_open') or 0) |
| 34339 | read_only | oi_close = float(feature_data.get('coinank_openInterest_kline_data_0_close') or 0) |
| 34350 | read_only | feature_data.get('coinank_funding_rate') |
| 34351 | read_only | or feature_data.get('coinank_fundingRate_indicator_data_0_fundingRate') |
| 34352 | read_only | or feature_data.get('coinank_fundingRate_indicator_data_0_fr') |
| 34353 | read_only | or feature_data.get('coinank_fundingRate_kline_data_0_close') |
| 34362 | read_only | feature_data.get('coinank_long_short_ratio') |
| 34363 | read_only | or feature_data.get('coinank_ls_global_account_ratio_longShortRatio_mean') |
| 34364 | read_only | or feature_data.get('coinank_ls_global_account_ratio_longShortRatio_first') |
| 34365 | read_only | or feature_data.get('coinank_ls_toptrader_accounts_longShortRatio_mean') |
| 34366 | read_only | or feature_data.get('coinank_ls_toptrader_accounts_longShortRatio_first') |
| 34391 | read_only | rsi = float(feature_data.get('ta_rsi', 50)) |
| 34398 | read_only | macd = float(feature_data.get('ta_macd', 0)) |
| 34399 | read_only | macd_signal = float(feature_data.get('ta_macd_signal', 0)) |
| 34406 | read_only | bb_upper = float(feature_data.get('ta_bb_upper', 0)) |
| 34407 | read_only | bb_lower = float(feature_data.get('ta_bb_lower', 0)) |
| 34408 | read_only | price = float(feature_data.get('price', 0)) |
| 34415 | read_only | volume_sma = float(feature_data.get('ta_volume_sma', 0)) |
| 34416 | read_only | current_volume = float(feature_data.get('volume', 0)) |
| 34432 | read_only | price_change_1h = float(feature_data.get('price_change_1h', 0)) |
| 34433 | read_only | price_change_24h = float(feature_data.get('price_change_24h', 0)) |
| 34444 | read_only | support = float(feature_data.get('support_level', 0)) |
| 34445 | read_only | resistance = float(feature_data.get('resistance_level', 0)) |
| 34446 | read_only | price = float(feature_data.get('price', 0)) |
| 34462 | read_only | # Get current features from Redis |
| 34464 | read_only | if not hasattr(self, '_signal_redis'): |
| 34467 | read_only | feature_data = self._signal_redis.hgetall(feature_key) |
| 34506 | read_only | family_scores[family] = family_scores.get(family, 0) + importance |
| 34537 | read_only | symbol_conf = SYMBOL_LEVERAGE_CONFIG.get(symbol, {}) |
| 34538 | read_only | default_cap = float(symbol_conf.get("max_leverage", 25.0 if symbol not in majors else 100.0)) |
| 34539 | read_only | default_min = float(symbol_conf.get("min_leverage", 1.0)) |
| 34556 | read_only | symbol_cap = min(symbol_cap, float(symbol_conf.get("max_leverage", symbol_cap))) |
| 34597 | read_only | default_min = float(SYMBOL_LEVERAGE_CONFIG.get(symbol, {}).get("min_leverage", 1.0)) |
| 34605 | read_only | event_type = event.get("event_type") |
| 34606 | read_only | direction = event.get("direction") |
| 34607 | read_only | severity = float(event.get("severity", 0.0) or 0.0) |
| 34608 | read_only | pos_side = str(current_pos.get("side") or current_pos.get("position_side") or current_pos.get("positionSide") or "UNKNOWN").upper() |
| 34609 | read_only | pos_pnl_pct = float(current_pos.get("pnl_percentage") or current_pos.get("pnl_pct") or 0.0) |
| 34655 | read_only | equity = float(portfolio.get("total_balance") or portfolio.get("available_balance") or 0.0) |
| 34656 | read_only | sizing_ctx = {"equity": equity, "available_balance": portfolio.get("available_balance", 0.0)} |
| 34705 | read_only | "fast_lane_event_id": event.get("event_id"), |
| 34706 | read_only | "fast_lane_event_type": event.get("event_type"), |
| 34707 | read_only | "fast_lane_severity": event.get("severity"), |
| 34708 | read_only | "fast_lane_direction": event.get("direction"), |
| 34709 | read_only | "intrabar_snapshot": event.get("intrabar_snapshot", {}), |
| 34710 | read_only | "reason_codes": event.get("trigger_reasons", []), |
| 34712 | read_only | "target_side": current_pos.get("side", "LONG"), |
| 34747 | write_signal | def attach_signal_publisher(self, redis_client, min_conf: float): |
| 34748 | write_metric | """TODO: attach a publisher (stream + last-hash) to PPO""" |
| 34749 | read_only | self._signal_redis = redis_client |
| 34752 | read_only | # AMBER #6: Standardize Redis client - inject into config for all feature readers |
| 34753 | read_only | self.config.redis_client = self._signal_redis |
| 34759 | read_only | self.feedback_tracker, self.signal_validator, self.feedback_consumer = initialize_feedback_system(self._signal_redis) |
| 34794 | write_signal | logger.info(f"✅ Signal publisher attached (Redis stream + last-hash, min_conf={min_conf})") |
| 34795 | read_only | logger.info(f"✅ Redis client standardized: all feature readers use self._signal_redis") |
| 34803 | write_signal | """Group signals by symbol before publishing (Production TA Section 1) |
| 34907 | read_only | # best = max(signal_list, key=lambda x: timeframe_order.get(x['timeframe'], 0)) |
| 34911 | read_only | # best = max(signal_list, key=lambda x: x['confidence'] * weights.get(x['timeframe'], 1)) |
| 34955 | read_only | if not pos.get('has_position'): |
| 34958 | read_only | current_side = pos.get('side')  # 'LONG' or 'SHORT' |
| 34978 | read_only | last_flip = self._last_flip_time.get(symbol, 0) |
| 35063 | read_only | _r = getattr(self, '_signal_redis', None) |
| 35070 | read_only | _raw = _r.hget(f"portfolio:positions:{_aid}", f"{symbol}:{_pos_side}") |
| 35075 | read_only | if float(_pdata.get("size", 0) or 0) > 0: |
| 35091 | read_only | "confidence": float(weighted_chosen.get("model_confidence", 0)), |
| 35093 | read_only | "model_confidence": float(weighted_chosen.get("model_confidence", 0)), |
| 35121 | read_only | return str(p.get("action_name") or p.get("action") or p.get("predicted_action") or "").upper() |
| 35132 | read_only | _pd = str(p.get("predicted_action") or "").upper() |
| 35135 | read_only | p_tf = str(p.get("timeframe") or p.get("tf") or "").strip() |
| 35136 | read_only | p_conf = float(p.get("model_confidence", 0) or 0) |
| 35137 | read_only | p_w = _tf_weights_h.get(p_tf, 0.15) |
| 35165 | read_only | best_minority = max(minority, key=lambda p: p.get("model_confidence", 0)) |
| 35169 | read_only | _htf = str(hedge_payload.get("timeframe") or "") |
| 35185 | read_only | _orig_margin = float(hedge_payload.get("margin_usd") or 0) |
| 35189 | read_only | _orig_notional = float(hedge_payload.get("notional_usd") or 0) |
| 35197 | read_only | float(best_minority.get("model_confidence", 0)), |
| 35208 | read_only | _r = getattr(self, '_signal_redis', None) |
| 35211 | read_only | _active_raw = _r.hgetall(_active_hedges_key) |
| 35220 | read_only | _ptf = str(p.get("timeframe") or "").strip() |
| 35221 | read_only | _pact = str(p.get("predicted_action") or "").upper() |
| 35227 | read_only | _cur_tf_dir = _now_dirs.get(_src_tf, "") |
| 35232 | read_only | if str(_acp.get("timeframe") or "").strip() == _src_tf: |
| 35233 | read_only | _ac_conf = float(_acp.get("model_confidence", 0) or 0) or 0.5 |
| 35255 | read_only | for _hp in [p for p in final if p.get("tf_hedge_disagg") and not p.get("tf_hedge_auto_close") and p.get("symbol") == symbol]: |
| 35256 | read_only | _stf = str(_hp.get("tf_hedge_source_tf") or "") |
| 35257 | read_only | _hdir = str(_hp.get("predicted_action") or "").upper() |
| 35259 | write_metric | _r.hset(_active_hedges_key, _stf, _hdir) |
| 35359 | read_only | _pos = _rp.get(symbol) or _rp.get(f"{symbol}_LONG") or _rp.get(f"{symbol}_SHORT") or \ |
| 35360 | read_only | _rp.get(f"{symbol}:LONG") or _rp.get(f"{symbol}:SHORT") |
| 35361 | read_only | if _pos and abs(float(_pos.get('size', 0) or _pos.get('positionAmt', 0) or 0)) > 0: |
| 35371 | read_only | p_conf = p.get('model_confidence', 0) |
| 35372 | read_only | p_tf = str(p.get('source_tf') or p.get('timeframe') or 'multi') |
| 35384 | read_only | _mc_sample = [(p.get('model_confidence'), p.get('source_tf'), p.get('action_name', p.get('action'))) for p in payload_list[:4]] |
| 35389 | write_risk_state | # WHY_NO_OPEN_RISK: no publishable candidate survived deconfliction input filter |
| 35404 | read_only | return str(p.get("action_name") or p.get("action") or p.get("predicted_action") or "").upper() |
| 35418 | read_only | cat = str(p.get("action_category") or "").upper() |
| 35425 | read_only | if str(p.get("predicted_action") or "").upper() in ("LONG", "SHORT"): |
| 35431 | read_only | chosen = max(non_entry, key=lambda p: p.get("model_confidence", 0)) |
| 35432 | read_only | _best_ne_conf = float(chosen.get("model_confidence", 0) or 0) |
| 35439 | write_metric | _close_tfs = set() |
| 35440 | write_metric | _close_tfs_non_1m = set() |
| 35442 | read_only | _ne_tf = str(_ne_p.get("timeframe") or _ne_p.get("tf") or "").strip() |
| 35454 | read_only | # Reads real position data from Redis portfolio:positions. |
| 35477 | read_only | _rc = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 35483 | read_only | _raw_pos = _rc.hget(_pkey, f"{symbol}:{_leg_side}") |
| 35493 | read_only | _pd.get("pnl_pct") or _pd.get("pnl_percentage") |
| 35494 | read_only | or _pd.get("roi_pct") or 0 |
| 35496 | read_only | _this_lev = float(_pd.get("leverage") or _pd.get("lev") or 1.0) |
| 35557 | read_only | _p_action = str(p.get('predicted_action') or p.get('action_name') or '').upper() |
| 35558 | read_only | _p_conf = float(p.get('model_confidence', 0) or 0) |
| 35559 | read_only | _p_tf = str(p.get('timeframe') or '5m') |
| 35560 | read_only | _p_w = _tf_w.get(_p_tf, 0.15) |
| 35586 | read_only | weighted_chosen = _long_best if _long_best else max(filtered, key=lambda p: p.get('model_confidence', 0)) |
| 35591 | read_only | weighted_chosen = _short_best if _short_best else max(filtered, key=lambda p: p.get('model_confidence', 0)) |
| 35596 | read_only | weighted_chosen = max(filtered, key=lambda p: p.get('model_confidence', 0)) |
| 35597 | read_only | _majority_dir = str(weighted_chosen.get('predicted_action', '')).upper() |
| 35598 | read_only | _majority_score = float(weighted_chosen.get('model_confidence', 0)) |
| 35610 | read_only | tf = str(p.get("timeframe") or p.get("tf") or "").strip() |
| 35616 | read_only | if "LONG" in act or str(p.get("predicted_action") or "").upper() == "LONG": |
| 35618 | read_only | elif "SHORT" in act or str(p.get("predicted_action") or "").upper() == "SHORT": |
| 35622 | read_only | "confidence": float(p.get("model_confidence", p.get("confidence", 0.0)) or 0.0), |
| 35623 | read_only | "entropy": float(p.get("entropy", 0.0) or 0.0), |
| 35643 | read_only | trend_dir = str(reg.get("trend_direction") or reg.get("trend_dir") or "NEUTRAL").upper() |
| 35645 | read_only | trend_strength = float(reg.get("trend_strength", reg.get("strength", 0.0)) or 0.0) |
| 35668 | write_metric | timing_candidates = [p for p in entry_like if str(p.get("timeframe") or p.get("tf") or "").strip() in set(timing_tfs)] |
| 35671 | read_only | legacy_best = max(entry_like, key=lambda p: p.get("model_confidence", 0)) |
| 35678 | read_only | f"[DECONFLICT] {symbol} → {weighted_chosen.get('predicted_action', 'UNKNOWN')} " |
| 35679 | read_only | f"(conf={float(weighted_chosen.get('model_confidence', 0)):.3f}, " |
| 35680 | read_only | f"tf={weighted_chosen.get('timeframe', 'multi')}) " |
| 35698 | read_only | conf_lb = float(legacy_best.get("model_confidence", 0.0) or 0.0) |
| 35726 | read_only | timing_best = max(timing_candidates, key=lambda p: p.get("model_confidence", 0)) |
| 35728 | read_only | timing_dir = "LONG" if ("LONG" in _action_name(timing_best) or str(timing_best.get("predicted_action") or "").upper() == "LONG") else "SHORT" |
| 35731 | read_only | if float(legacy_best.get("model_confidence", 0.0) or 0.0) >= float(INTENT_ALLOW_DIRECT_ENTRY_ULTRA_CONF): |
| 35759 | read_only | r = getattr(self, "_signal_redis", None) |
| 35761 | read_only | msnap = r.hgetall(f"msnap:coinapi_wsds:{symbol}") or {} |
| 35772 | read_only | micro[k] = msnap.get(k) |
| 35774 | read_only | micro["spread_bps"] = msnap.get("spread") |
| 35781 | read_only | _timing_is_1m = str(timing_best.get("timeframe") or timing_best.get("tf") or "").strip() == "1m" |
| 35783 | read_only | _fms = float(micro.get("fast_move_score", 0) or 0) |
| 35784 | read_only | _imb5 = abs(float(micro.get("imbalance_5", 0) or 0)) |
| 35785 | read_only | _churn = float(micro.get("churn_score", 0) or 0) |
| 35792 | read_only | if float(legacy_best.get("model_confidence", 0.0) or 0.0) >= float(INTENT_ALLOW_DIRECT_ENTRY_ULTRA_CONF): |
| 35814 | read_only | confidence=float(timing_best.get("model_confidence", 0.0) or 0.0), |
| 35835 | read_only | confidence=float(timing_best.get("model_confidence", 0.0) or 0.0), |
| 35839 | read_only | entropy=float(timing_best.get("entropy", 0.0) or 0.0), |
| 35872 | read_only | _allow_taker_1m = float(micro.get("fast_move_score", 0) or 0) > 0.6 |
| 35876 | read_only | sm = timing_best.get("signal_meta") |
| 35907 | read_only | final_conf = chosen.get('model_confidence', 0) |
| 35908 | read_only | final_action = chosen.get('predicted_action', 'UNKNOWN') |
| 35909 | read_only | final_tf = chosen.get('timeframe', 'multi') |
| 35911 | read_only | signal_details = [(p.get('timeframe', '?'), p.get('predicted_action', '?'), round(p.get('model_confidence', 0), 3)) for p in payload_list] |
| 35932 | read_only | _prev = self._dedup_last.get(_dk) |
| 35950 | read_only | _chosen_is_disagg_only = bool(chosen.get("_disagg_only")) |
| 35974 | read_only | redis_conn = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 35975 | read_only | if not redis_conn: |
| 35977 | read_only | builder = MTFPositionBuilder(redis_conn) |
| 35981 | read_only | raw_eq = redis_conn.get(f"portfolio:equity:{aid_key}") |
| 35987 | read_only | symbols_in_final = {p.get("symbol") for p in final if p.get("symbol")} |
| 35992 | read_only | tf = p.get("timeframe", "") |
| 35995 | read_only | "action_idx": int(p.get("action_idx", 0)), |
| 35996 | read_only | "confidence": float(p.get("confidence", 0)), |
| 35997 | read_only | "action": p.get("action_name") or p.get("action", ""), |
| 36004 | read_only | pos_raw = redis_conn.hgetall(f"portfolio:positions:primary") |
| 36011 | read_only | current_hedge_margin += abs(float(pos_d.get("margin", 0) or 0)) |
| 36032 | write_metric | Tracks the last published direction per symbol. If direction flips within |
| 36044 | write_metric | if not hasattr(self, '_last_published_direction'): |
| 36045 | write_metric | self._last_published_direction = {}  # symbol -> (direction, ts) |
| 36051 | read_only | symbol = sig.get('symbol', '') |
| 36052 | read_only | action_name = sig.get('action_name', sig.get('action', '')) |
| 36053 | read_only | confidence = float(sig.get('model_confidence', sig.get('confidence', 0))) |
| 36063 | write_metric | last = self._last_published_direction.get(symbol) |
| 36090 | write_metric | self._last_published_direction[symbol] = (direction, now) |
| 36114 | read_only | predicted_return = sig.get('predicted_return') |
| 36129 | read_only | action_name = str(sig.get('action_name', sig.get('action', ''))).upper() |
| 36140 | read_only | sym = sig.get('symbol', '?') |
| 36141 | read_only | conf = float(sig.get('confidence', sig.get('model_confidence', 0))) |
| 36144 | read_only | tf_bias_dir = sig.get('tf_bias_dir', 0) |
| 36205 | read_only | analyzer = get_proactive_analyzer(redis_client=self._signal_redis) |
| 36206 | read_only | overlay = get_microstructure_overlay(redis_client=self._signal_redis) if is_overlay_enabled() else None |
| 36222 | read_only | sym = str(p.get("symbol") or "").upper() |
| 36223 | read_only | side = str(p.get("side") or p.get("positionSide") or "").upper() |
| 36224 | read_only | acct = str(p.get("account_id") or p.get("source") or "").strip().lower() |
| 36259 | read_only | sym = str(s.get("symbol") or "").upper() |
| 36262 | read_only | act = str(s.get("action") or s.get("action_name") or s.get("predicted_action") or "").upper() |
| 36264 | read_only | conf = float(s.get("model_confidence", s.get("confidence", 0.0)) or 0.0) |
| 36277 | read_only | return float(acct_equity_cache.get(aid, 0.0) or 0.0) |
| 36280 | read_only | raw = self._signal_redis.get(f"portfolio:equity:{aid}") if self._signal_redis else None |
| 36285 | read_only | eq = float(pdata.get("equity_usd", 0.0) or 0.0) |
| 36291 | read_only | eq = float(st.get("total_balance", 0.0) or st.get("margin_balance", 0.0) or 0.0) |
| 36303 | read_only | symbol = signal.get('symbol', '') |
| 36304 | read_only | action = str(signal.get('action') or signal.get('action_name') or signal.get('predicted_action') or '').upper() |
| 36305 | read_only | confidence = float(signal.get('confidence', 0.5)) |
| 36306 | read_only | timeframe = signal.get('timeframe', '5m') |
| 36310 | read_only | req_acct = str(signal.get("account_id") or signal.get("account") or signal.get("target_account_id") or "").strip().lower() |
| 36317 | read_only | legs = pos_by_acct_sym.get((req_acct, sym_u), {}) or {} |
| 36320 | read_only | if "LONG" in act_u and legs.get("LONG"): |
| 36321 | read_only | pos_info = legs.get("LONG") or {} |
| 36322 | read_only | elif "SHORT" in act_u and legs.get("SHORT"): |
| 36323 | read_only | pos_info = legs.get("SHORT") or {} |
| 36329 | read_only | n = abs(float((pd or {}).get("notional", 0.0) or 0.0)) |
| 36336 | read_only | position_side = str(pos_info.get("side") or pos_info.get("positionSide") or "").upper() |
| 36341 | read_only | pnl_pct = float(pos_info.get("pnl_percentage", 0.0) or pos_info.get("pnl_pct", 0.0) or 0.0) |
| 36346 | read_only | position_size_usd = abs(float(pos_info.get("notional", 0.0) or 0.0)) |
| 36352 | read_only | upnl = float(pos_info.get("unrealized_pnl", 0.0) or pos_info.get("unrealizedProfit", 0.0) or 0.0) |
| 36398 | read_only | # Dedupe check via Redis |
| 36400 | read_only | dedupe_ttl = dedupe_ttl_by_tf.get(alert_tf, 120) |
| 36403 | read_only | already_sent = self._signal_redis.get(dedupe_key) |
| 36425 | read_only | self._signal_redis.setex(dedupe_key, dedupe_ttl, '1') |
| 36466 | write_metric | # Publish proactive alert to Redis |
| 36467 | write_metric | analyzer.publish_to_redis(proactive_alert) |
| 36474 | read_only | if timeframe == '1m' and not position_side and not (ENABLE_INTENT_TIMING_STACK and bool(signal.get("intent_timing_entry"))): |
| 36488 | read_only | position_size_pct=float(signal.get('position_size_pct', 0)), |
| 36496 | read_only | signal['margin_usd'] = float(signal.get('margin_usd', 0)) * result.size_multiplier |
| 36497 | read_only | signal['notional_usd'] = float(signal.get('notional_usd', 0)) * result.size_multiplier |
| 36533 | read_only | raw_active = self._signal_redis.get(f"hedge:active:{sym}:{acct}") if self._signal_redis else None |
| 36538 | read_only | ms = str(hinfo.get("main_position_side") or "").upper() |
| 36548 | read_only | pd = legs.get(sd) |
| 36552 | read_only | n = abs(float(pd.get("notional", 0.0) or 0.0)) |
| 36561 | read_only | pos_main = legs.get(main_side) |
| 36567 | read_only | pos_notional = abs(float(pos_main.get("notional", 0.0) or 0.0)) |
| 36574 | read_only | pos_main.get("size", 0.0) |
| 36575 | read_only | or pos_main.get("position_amt", 0.0) |
| 36576 | read_only | or pos_main.get("qty", 0.0) |
| 36577 | read_only | or pos_main.get("amount", 0.0) |
| 36584 | read_only | pos_main.get("mark_price", 0.0) |
| 36585 | read_only | or pos_main.get("current_price", 0.0) |
| 36586 | read_only | or pos_main.get("price", 0.0) |
| 36597 | read_only | pnl_pct_main = float(pos_main.get("pnl_percentage", 0.0) or pos_main.get("pnl_pct", 0.0) or 0.0) |
| 36602 | read_only | upnl = float(pos_main.get("unrealized_pnl", 0.0) or 0.0) |
| 36609 | read_only | m_act, m_conf = model_by_symbol.get(sym, ("", 0.0)) |
| 36624 | write_metric | # Publish alert for observability (account-scoped) |
| 36626 | write_metric | analyzer.publish_to_redis(proactive_alert) |
| 36648 | read_only | hedge_notional = float((proactive_alert.trigger_metrics or {}).get("hedge_notional_usd", 0.0) or 0.0) |
| 36653 | read_only | pct = float((proactive_alert.trigger_metrics or {}).get("hedge_size_pct", 0.0) or 0.0) |
| 36661 | read_only | sym_min = float((BINANCE_FUTURES_MIN_NOTIONAL_USD_BY_SYMBOL or {}).get(sym, MIN_NOTIONAL_USD) or MIN_NOTIONAL_USD) |
| 36682 | read_only | lev = float(pos_main.get("leverage", 0.0) or 0.0) |
| 36687 | read_only | lev_cfg = SYMBOL_LEVERAGE_CONFIG.get(sym, SYMBOL_LEVERAGE_CONFIG.get("default", {})) or {} |
| 36688 | read_only | lev = float(lev_cfg.get("min_leverage", 10) or 10) |
| 36751 | read_only | p_symbol = p_signal.get('symbol', '') |
| 36752 | read_only | p_action = str(p_signal.get('action') or p_signal.get('action_name') or '').upper() |
| 36753 | read_only | p_tf = p_signal.get('timeframe', '5m') |
| 36756 | write_metric | # which is symbol-scoped and not account-scoped. Publish hedges as-is (account_id already stamped). |
| 36759 | read_only | bool(p_signal.get("hedge_intent")) |
| 36760 | read_only | or str(p_signal.get("action_category") or "").upper() == "HEDGE" |
| 36773 | read_only | p_conf = float(p_signal.get('confidence', 0.6)) |
| 36778 | read_only | position_size_pct=float(p_signal.get('position_size_pct', 0)), |
| 36786 | read_only | p_signal['margin_usd'] = float(p_signal.get('margin_usd', 0)) * result.size_multiplier |
| 36787 | read_only | p_signal['notional_usd'] = float(p_signal.get('notional_usd', 0)) * result.size_multiplier |
| 36795 | read_only | logger.info(f"[PROACTIVE_HEDGE] ✅ {p_symbol}:{p_tf} {p_action} (acct={p_signal.get('account_id')}) bypass TEC → tradeable") |
| 36831 | read_only | Duplicate suppression: Check Redis keys last_action:{symbol}:{category} |
| 36871 | read_only | symbol = sig.get('symbol', '') |
| 36872 | read_only | category = sig.get('action_category', 'UNKNOWN') |
| 36873 | read_only | tf = sig.get('timeframe', '5m') |
| 36874 | read_only | conf = float(sig.get('confidence', 0.0)) |
| 36880 | read_only | logger.warning(f"[AGGREGATION_INPUT] UNKNOWN category: {symbol} {tf} action={sig.get('action')} conf={conf:.3f}") |
| 36891 | read_only | 'priority': TF_PRIORITY.get(category, {}).get(tf, 0) |
| 36917 | read_only | ttl_sec = TTL_MAP.get(category, 0) |
| 36920 | write_metric | last_ts = self._last_published_ts.get(key, 0) |
| 36926 | read_only | is_flash_hedge = winner['payload'].get('flash_hedge', False) |
| 36933 | read_only | winner['payload'].get('bypass_gating') |
| 36934 | read_only | or winner['payload'].get('force_execute') |
| 36935 | read_only | or winner['payload'].get('gating_override') |
| 36944 | read_only | is_flash_hedge = winner['payload'].get('flash_hedge', False) |
| 36953 | read_only | is_over_budget, budget_reason = self._check_budget(symbol, category) |
| 36957 | read_only | is_flash_hedge = winner['payload'].get('flash_hedge', False) |
| 36965 | read_only | action_name = winner['payload'].get('action', '') |
| 36970 | read_only | acct = (winner.get('payload') or {}).get('account_id') |
| 36999 | read_only | acct = (winner.get('payload') or {}).get('account_id') |
| 37010 | read_only | winner['payload'].get('equity_usd') |
| 37011 | read_only | or winner['payload'].get('total_margin_balance') |
| 37012 | read_only | or self._margin_metrics.get('total_margin_balance', 0.0) |
| 37017 | read_only | margin_usd = float(winner['payload'].get('margin_usd') or 0.0) |
| 37021 | read_only | if winner['payload'].get('notional_usd') is not None: |
| 37022 | read_only | winner['payload']['notional_usd'] = float(winner['payload'].get('notional_usd') or 0.0) * scale |
| 37023 | read_only | if winner['payload'].get('position_size_pct') is not None: |
| 37024 | read_only | winner['payload']['position_size_pct'] = float(winner['payload'].get('position_size_pct') or 0.0) * scale |
| 37035 | read_only | is_flash_hedge = winner['payload'].get('flash_hedge', False) |
| 37051 | read_only | stack = trainer_ref._tf_stack.get(symbol, {}) |
| 37052 | read_only | if stack.get('exec_gate') is not None: |
| 37060 | read_only | is_flash_hedge = winner['payload'].get('flash_hedge', False) |
| 37087 | write_metric | # Winner selected - DO NOT update timestamp here (moved to post-publish) |
| 37092 | write_metric | # Store the key for post-publish timestamp update |
| 37096 | read_only | is_flash_hedge = winner['payload'].get('flash_hedge', False) |
| 37098 | read_only | flash_pct = winner['payload'].get('flash_move_pct', 0.0) |
| 37099 | read_only | action_name = winner['payload'].get('action_name', 'UNKNOWN') |
| 37100 | write_signal | logger.warning(f"✅ [FLASH_HEDGE_PUBLISHED] {symbol} {action_name} / " |
| 37107 | read_only | open_risk_count = sum(1 for s in aggregated if s.get('action_category') == 'OPEN_RISK') |
| 37108 | read_only | hedge_count = sum(1 for s in aggregated if s.get('action_category') == 'HEDGE') |
| 37109 | read_only | protective_count = sum(1 for s in aggregated if s.get('action_category') == 'PROTECTIVE') |
| 37133 | read_only | action = payload.get('predicted_action') |
| 37138 | write_metric | # HARDENING (Jan 2026): trust trader-published positions over stale caches. |
| 37141 | read_only | preferred_account_id = str(payload.get('account_id') or 'primary').strip().lower() |
| 37151 | read_only | p0 = tp.get(k) or {} |
| 37152 | read_only | if abs(float(p0.get("size", 0) or 0.0)) > 0.0: |
| 37160 | read_only | if str(p0.get("symbol") or "") == str(symbol) and abs(float(p0.get("size", 0) or 0.0)) > 0.0: |
| 37170 | read_only | if not pos.get('has_position'): |
| 37177 | read_only | action_name = payload.get('action_name') or payload.get('action') or action |
| 37181 | read_only | action_name = action_map.get(action_name, 'UNKNOWN') |
| 37185 | read_only | current_side = pos.get('side')  # 'LONG' or 'SHORT' |
| 37186 | read_only | position_source = pos.get('source', 'unknown') |
| 37199 | write_signal | # If payload has no account_id (model signals), default to primary (matches publish routing). |
| 37200 | read_only | preferred_account_id = str(payload.get('account_id') or 'primary').strip().lower() |
| 37204 | read_only | redis_client = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 37205 | read_only | if not redis_client: |
| 37206 | read_only | return float(pos.get('pnl_pct', 0) or pos.get('unrealized_pnl_pct', 0) or 0) |
| 37207 | read_only | raw = redis_client.hget(f"portfolio:positions:{account_id}", f"{symbol}:{side}") |
| 37209 | read_only | return float(pos.get('pnl_pct', 0) or pos.get('unrealized_pnl_pct', 0) or 0) |
| 37212 | read_only | return float(leg.get('pnl_pct', 0) or leg.get('unrealized_pnl_pct', 0) or 0) |
| 37214 | read_only | return float(pos.get('pnl_pct', 0) or pos.get('unrealized_pnl_pct', 0) or 0) |
| 37217 | read_only | current_exposure_pct = float(pos.get('margin_pct', 0) or pos.get('exposure_pct', 0) or 0) |
| 37221 | read_only | margin_used = float(pos.get('margin_used', 0) or pos.get('margin', 0) or pos.get('initialMargin', 0) or 0) |
| 37234 | read_only | rc0 = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 37235 | read_only | eq_raw0 = rc0.get(f"portfolio:equity:{preferred_account_id}") if rc0 else None |
| 37238 | read_only | eq_usd0 = float((eqj0 or {}).get("equity_usd", 0.0) or 0.0) |
| 37239 | read_only | avail0 = float((eqj0 or {}).get("available_margin_usd", 0.0) or 0.0) |
| 37303 | read_only | _ate_ec = get_adaptive_engine(redis_client=self.redis) |
| 37304 | read_only | _ate_ec_lev = float(payload.get("leverage", 20) or 20) |
| 37448 | read_only | logger.info(f"[DECONFLICT] {symbol} duplicate {current_side} suppressed (already open in {position_source}, conf={payload.get('model_confidence', 0):.3f})") |
| 37459 | read_only | conf = float(payload.get('model_confidence', 0) or payload.get('confidence', 0) or 0) |
| 37460 | read_only | position_pnl_pct = float(pos.get('pnl_pct', 0) or pos.get('pnl_percentage', 0) or 0) |
| 37497 | read_only | tf_summary = payload.get('tf_summary', {}) |
| 37506 | read_only | tf_1m = tf_summary.get('1m', {}) |
| 37507 | read_only | tf_5m = tf_summary.get('5m', {}) |
| 37509 | read_only | tf_1m_action = str(tf_1m.get('action', tf_1m.get('predicted_action', ''))).upper() if isinstance(tf_1m, dict) else '' |
| 37510 | read_only | tf_5m_action = str(tf_5m.get('action', tf_5m.get('predicted_action', ''))).upper() if isinstance(tf_5m, dict) else '' |
| 37511 | read_only | tf_1m_conf = float(tf_1m.get('confidence', tf_1m.get('model_confidence', 0)) or 0) if isinstance(tf_1m, dict) else 0 |
| 37512 | read_only | tf_5m_conf = float(tf_5m.get('confidence', tf_5m.get('model_confidence', 0)) or 0) if isinstance(tf_5m, dict) else 0 |
| 37526 | read_only | spoof_score = float(payload.get('spoof_score', 0) or 0) |
| 37527 | read_only | fast_move_score = float(payload.get('fast_move_score', 0) or 0) |
| 37533 | read_only | spoof_score = micro.get('spoof_score', 0) |
| 37534 | read_only | fast_move_score = micro.get('fast_move_score', 0) |
| 37562 | read_only | is_flash = micro.get('is_flash_move', False) |
| 37563 | read_only | flash_pct = micro.get('flash_move_pct', 0.0) |
| 37564 | read_only | flash_dir = micro.get('flash_move_direction', None) |
| 37568 | read_only | last_flash_ts = self.redis_client.get(cooldown_key) |
| 37580 | read_only | self.redis_client.setex(cooldown_key, FLASH_HEDGE_COOLDOWN_SECONDS, str(current_time)) |
| 37594 | read_only | old_action = payload.get('action_name', 'OPEN_SHORT') |
| 37600 | read_only | aid = str(payload.get("account_id") or payload.get("account") or "primary").strip().lower() |
| 37605 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 37606 | read_only | raw_leg = rc.hget(f"portfolio:positions:{aid}", f"{symbol}:{hedge_side}") if rc else None |
| 37611 | read_only | exists = abs(float((leg or {}).get("size", 0) or 0.0)) > 1e-12 |
| 37650 | read_only | payload['flash_move_pct'] = micro.get('flash_move_pct', 0.0) |
| 37671 | read_only | old_action = payload.get('action_name', 'OPEN_LONG') |
| 37676 | read_only | aid = str(payload.get("account_id") or payload.get("account") or "primary").strip().lower() |
| 37680 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 37681 | read_only | raw_leg = rc.hget(f"portfolio:positions:{aid}", f"{symbol}:{hedge_side}") if rc else None |
| 37686 | read_only | exists = abs(float((leg or {}).get("size", 0) or 0.0)) > 1e-12 |
| 37743 | read_only | if 'action_category' not in payload or payload.get('action_category') == 'UNKNOWN': |
| 37744 | read_only | action_name = payload.get('action_name') or payload.get('final_action') or payload.get('action') or str(action or '') |
| 37747 | read_only | action_name = action_map.get(action_name, 'UNKNOWN') |
| 37754 | read_only | def _parse_redis_price(redis_client, symbol: str) -> float: |
| 37755 | read_only | """Parse price from Redis, handling both JSON and plain float formats.""" |
| 37758 | read_only | raw = redis_client.get(key) |
| 37778 | read_only | raw = redis_client.get(f"latest:[REDACTED]:mark_price:{symbol}") |
| 37783 | read_only | v = float(d.get("mark_price", 0)) |
| 37791 | write_signal | """Record a published prediction for later accuracy evaluation.""" |
| 37794 | read_only | symbol = payload.get('symbol', '') |
| 37795 | read_only | action = payload.get('action_name', payload.get('action', '')) |
| 37796 | read_only | confidence = float(payload.get('model_confidence', payload.get('confidence', 0))) |
| 37797 | read_only | timeframe = payload.get('timeframe', '5m') |
| 37803 | read_only | redis_client = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 37804 | read_only | if not redis_client: |
| 37807 | read_only | current_price = self._parse_redis_price(redis_client, symbol) |
| 37816 | write_signal | redis_client.lpush('prediction:accuracy:pending', record) |
| 37817 | read_only | redis_client.ltrim('prediction:accuracy:pending', 0, 999) |
| 37830 | read_only | redis_client = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 37831 | read_only | if not redis_client: |
| 37834 | read_only | pending = redis_client.lrange('prediction:accuracy:pending', 0, -1) |
| 37849 | read_only | age = now - float(rec.get('ts', now)) |
| 37850 | read_only | tf = rec.get('timeframe', 'multi') |
| 37851 | read_only | eval_sec = _TF_EVAL_SEC.get(tf, 300) |
| 37862 | read_only | confidence = float(rec.get('confidence', 0)) |
| 37864 | read_only | current_price = self._parse_redis_price(redis_client, symbol) |
| 37892 | read_only | pipe = redis_client.pipeline() |
| 37893 | write_signal | pipe.delete('prediction:accuracy:pending') |
| 37895 | write_signal | pipe.lpush('prediction:accuracy:pending', item) |
| 37899 | write_signal | redis_client.lpush('prediction:accuracy:results', json.dumps({ |
| 37904 | read_only | redis_client.ltrim('prediction:accuracy:results', 0, 199) |
| 37925 | read_only | self, symbol: str, category: str, redis_conn, |
| 37932 | read_only | msnap = redis_conn.hgetall(f"msnap:coinapi_wsds:{symbol}") |
| 37934 | read_only | _g = lambda k, d=0.0: float((msnap.get(k) or msnap.get(k.encode()) or d) if msnap else d) |
| 37961 | read_only | uf = redis_conn.hgetall(f"unified_features:{symbol}:{tf}") |
| 37965 | read_only | _gf = lambda k, d=0.0: float((uf.get(k) or uf.get(k.encode()) or d) if uf else d) |
| 37986 | write_signal | def _publish_buffered_signals(self, payloads: list) -> int: |
| 37987 | write_signal | """Publish deconflicted signal payloads to Redis stream |
| 37990 | write_signal | payloads: List of final signal payloads to publish |
| 37993 | write_signal | Number of signals published |
| 37998 | write_metric | published_count = 0 |
| 38005 | write_metric | # - When multiple entry candidates exist in the same cycle, publishing in static SYMBOLS order |
| 38011 | write_signal | # - Publish PROTECTIVE/HEDGE signals unchanged (never filtered), but reorder OPEN_RISK so the |
| 38035 | read_only | # Preload per-symbol realized volatility from Redis (fast pipeline). |
| 38036 | read_only | redis_client = ( |
| 38037 | read_only | getattr(self, "_signal_redis", None) |
| 38038 | read_only | or getattr(self, "redis", None) |
| 38043 | read_only | s = p.get("symbol") |
| 38048 | read_only | if redis_client is not None and hasattr(redis_client, "pipeline") and symbols_for_vol: |
| 38050 | read_only | pipe = redis_client.pipeline() |
| 38052 | read_only | pipe.hgetall(f"features:unified:{s}:{VOL_TF}") |
| 38060 | read_only | v = feat.get(cand) |
| 38075 | read_only | action_val = p.get("final_action") or p.get("action_name") or p.get("action") or "" |
| 38076 | read_only | category = str(p.get("action_category") or get_action_category(action_val)).upper() |
| 38081 | read_only | sym = str(p.get("symbol") or "") |
| 38084 | read_only | conf = p.get("confidence") |
| 38086 | read_only | conf = p.get("model_confidence", 0.0) |
| 38095 | read_only | # Volatility percent (prefer payload, otherwise Redis preload) |
| 38096 | read_only | vol_pct = p.get("volatility_pct") |
| 38098 | read_only | vol_pct = vol_by_symbol.get(sym, 0.0) |
| 38160 | write_risk_state | # Preserve safety ordering: publish non-open-risk first (protective/hedge), |
| 38169 | read_only | # Trader-side systems (stealth stops, dynamic TP, trailing) emit proposals to Redis. |
| 38173 | write_metric | # - In shadow mode, we still ingest proposals for proofing, but to avoid duplicate publishes, |
| 38174 | write_metric | #   we only publish proposals when ORCHESTRATOR_MODE == "publish". |
| 38190 | read_only | getattr(self, "_signal_redis", None) |
| 38191 | read_only | or getattr(self, "redis", None) |
| 38192 | read_only | or getattr(getattr(self, "ppo_model", None), "_signal_redis", None) |
| 38193 | read_only | or getattr(getattr(self, "ppo_model", None), "redis", None) |
| 38207 | read_only | raw = (fields or {}).get("data") or "{}" |
| 38228 | write_metric | # In shadow mode, orchestrator does NOT change what is published. To prevent |
| 38229 | write_metric | # duplicate/conflicting publishes, only include external proposals when mode=publish. |
| 38234 | write_metric | if str(ORCHESTRATOR_MODE or "shadow").strip().lower() == "publish": |
| 38238 | write_metric | # ORCHESTRATOR (Jan 2026): Single-publisher arbitration + trader-aligned feasibility |
| 38277 | write_checkpoint_metadata | # IMPORTANT: in this codebase, the canonical Redis publisher lives on ppo_model. |
| 38278 | read_only | # Use ppo_model redis clients as fallback so proofs are emitted even if HybridTrainer |
| 38279 | read_only | # does not carry _signal_redis directly. |
| 38280 | read_only | redis_client = ( |
| 38281 | read_only | getattr(self, "_signal_redis", None) |
| 38282 | read_only | or getattr(self, "redis", None) |
| 38283 | read_only | or getattr(getattr(self, "ppo_model", None), "_signal_redis", None) |
| 38284 | read_only | or getattr(getattr(self, "ppo_model", None), "redis", None) |
| 38286 | read_only | orch = TradePlanOrchestrator(redis_client=redis_client, cfg=config) |
| 38300 | write_metric | logger.warning(f"[ORCH] Orchestrator failed (fallback to legacy publish): {orch_err}") |
| 38302 | write_metric | # Emit proofs (shadow or publish) for auditing/debugging |
| 38307 | read_only | getattr(self, "_signal_redis", None) |
| 38308 | read_only | or getattr(self, "redis", None) |
| 38309 | read_only | or getattr(getattr(self, "ppo_model", None), "_signal_redis", None) |
| 38310 | read_only | or getattr(getattr(self, "ppo_model", None), "redis", None) |
| 38313 | read_only | # Fallback: create a new Redis connection for proof emission |
| 38315 | read_only | import redis as redis_lib |
| 38316 | read_only | from config import REDIS_HOST, REDIS_PORT, REDIS_DB |
| 38317 | read_only | r = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True) |
| 38318 | read_only | logger.debug("[ORCH_PROOF] Created fallback Redis connection for proof emission") |
| 38319 | read_only | except Exception as redis_err: |
| 38320 | read_only | logger.warning(f"[ORCH_PROOF] Failed to create fallback Redis: {redis_err}") |
| 38322 | write_metric | if r is not None and hasattr(r, "xadd"): |
| 38327 | write_metric | r.xadd(ORCHESTRATOR_PROOF_STREAM, {"data": json_lib.dumps(pr2, separators=(",", ":"))}) |
| 38331 | read_only | f"[ORCH_PROOF] acct={pr2.get('account_id')} sym={pr2.get('symbol')} " |
| 38332 | read_only | f"action={pr2.get('winner_action')} reason={pr2.get('reason')} " |
| 38333 | read_only | f"resized={bool(pr2.get('resized'))} dropped={bool(pr2.get('dropped'))} " |
| 38334 | read_only | f"pair_headroom=${float(pr2.get('pair_headroom_usd', 0.0) or 0.0):.2f}" |
| 38339 | read_only | logger.warning(f"[ORCH_PROOF] No Redis client available, {len(orchestrator_proofs)} proofs not emitted") |
| 38350 | write_signal | #   multiple OPEN_RISK signals published in the same cycle (execution is async). |
| 38391 | read_only | ts = obj.get("ts_ms") or obj.get("timestamp_ms") |
| 38392 | read_only | if ts is None and obj.get("timestamp") is not None: |
| 38393 | read_only | ts = float(obj.get("timestamp")) * 1000.0 |
| 38419 | read_only | nested = obj.get("data") |
| 38430 | read_only | eq = obj.get("equity_usd") |
| 38433 | read_only | if obj.get(k) is not None: |
| 38434 | read_only | eq = obj.get(k) |
| 38488 | write_metric | existing_syms = set(positions_dict.keys()) |
| 38517 | write_metric | existing_groups = set() |
| 38524 | write_metric | existing_groups = set() |
| 38542 | write_metric | "planned_symbols": set(),  # new symbols reserved in this publish cycle |
| 38544 | write_metric | "planned_groups": set(), |
| 38559 | write_metric | "published_count": 0, |
| 38565 | read_only | if float(open_risk_governor[aid].get("equity_usd", 0.0) or 0.0) <= 0.0: |
| 38566 | read_only | rc_eq = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 38567 | read_only | raw_eq = rc_eq.get(f"portfolio:equity:{aid}") if rc_eq else None |
| 38589 | write_checkpoint_metadata | payload['source'] = getattr(config, "PUBLISH_SOURCE_TAG", "trainer_deconflicted") |
| 38593 | write_signal | # FIX G: Refresh timestamps before publish to prevent STALE_SIGNAL_DROPPED |
| 38595 | write_signal | # Signals created at cycle-start have stale ts_ms by publish time. |
| 38600 | read_only | payload['_original_ts_ms'] = payload.get('ts_ms') or payload.get('created_ts_ms') or _now_pub_ms |
| 38613 | write_signal | # but the publisher incorrectly reverts to flip/open actions (breaking hedge-mode and starving asjad). |
| 38615 | read_only | payload.get("final_action") |
| 38616 | read_only | or payload.get("action_name") |
| 38617 | read_only | or payload.get("action") |
| 38618 | read_only | or payload.get("predicted_action") |
| 38628 | read_only | else {0: 'HOLD', 1: 'OPEN_LONG', 2: 'OPEN_SHORT', 3: 'CLOSE_LONG', 4: 'CLOSE_SHORT', 5: 'CLOSE_SHORT_OPEN_LONG', 6: 'CLOSE_LONG_OPEN_SHORT'}.get(int(raw_action) if isinstance(raw_action, (int, float)) else 0, 'HOLD') |
| 38643 | write_signal | # Skip HOLD/NO_ACTION - these should never be published |
| 38645 | write_signal | logger.debug(f"[PUBLISH_BUFFERED] Skipping HOLD action for {symbol}") |
| 38650 | write_metric | # If we just published a CLOSE for this symbol+direction, block |
| 38670 | read_only | _last_close = self._recent_closes.get(f"{symbol}:{_open_dir}", 0) |
| 38694 | write_metric | logger.warning(f"[PUBLISH_BUFFERED] Config import failed: {cfg_err}, using fallbacks") |
| 38705 | read_only | category = str(payload.get("action_category") or get_action_category(action_name)).upper() |
| 38709 | write_risk_state | # DECONFLICTION CHURN PROTECTION: Per-symbol publish cooldown |
| 38710 | write_signal | # After publishing ANY signal for a symbol, enforce cooldown before publishing |
| 38735 | read_only | _cooldown_redis = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 38736 | read_only | if _cooldown_redis: |
| 38737 | write_risk_state | _cooldown_key = f"trainer:deconflict:last_publish:{symbol}" |
| 38738 | read_only | _last_pub_raw = _cooldown_redis.get(_cooldown_key) |
| 38746 | read_only | symbol, category, _cooldown_redis, |
| 38760 | write_metric | symbol in (st0.get("existing_symbols") or set()) |
| 38767 | read_only | # Fallback: if governor snapshot isn't available, do a quick Redis position check. |
| 38785 | read_only | if hasattr(_cooldown_redis, "pipeline"): |
| 38786 | read_only | pipe = _cooldown_redis.pipeline() |
| 38787 | read_only | pipe.hget(key0, f"{sym_u}:LONG") |
| 38788 | read_only | pipe.hget(key0, f"{sym_u}:SHORT") |
| 38791 | read_only | raw_long = _cooldown_redis.hget(key0, f"{sym_u}:LONG") |
| 38792 | read_only | raw_short = _cooldown_redis.hget(key0, f"{sym_u}:SHORT") |
| 38815 | read_only | if k in d and abs(float(d.get(k) or 0.0)) > 0.0: |
| 38830 | write_risk_state | f"last publish {_age_sec:.0f}s ago < {_cooldown_sec:.0f}s cooldown" |
| 38832 | write_metric | self._publish_skip_event( |
| 38834 | write_signal | f"{symbol} {action_name} dropped: {_age_sec:.0f}s since last publish < {_cooldown_sec:.0f}s cooldown" |
| 38865 | read_only | aid = payload.get("account_id") or payload.get("account") or payload.get("target_account_id") or "" |
| 38879 | read_only | raw = self._signal_redis.get(f"portfolio:equity:{aid}") if getattr(self, "_signal_redis", None) else None |
| 38887 | read_only | "total_balance": float(obj.get("equity_usd", 0.0) or 0.0), |
| 38888 | read_only | "available_balance": float(obj.get("available_margin_usd", 0.0) or 0.0), |
| 38889 | read_only | "total_margin_used": float(obj.get("used_margin_usd", 0.0) or 0.0), |
| 38894 | read_only | conf = float(payload.get("model_confidence", payload.get("confidence", 0.0)) or 0.0) |
| 38895 | read_only | tox = float(payload.get("toxicity", 0.0) or 0.0) |
| 38900 | read_only | cur_margin = float(payload.get("margin_usd", 0.0) or 0.0) |
| 38910 | read_only | payload["notional_usd"] = float(payload.get("notional_usd", 0.0) or 0.0) * float(scale) |
| 38914 | read_only | payload["position_size_pct"] = float(payload.get("position_size_pct", 0.0) or 0.0) * float(scale) |
| 38938 | write_risk_state | # JAN6 GOVERNOR PATH: Publish OPEN_RISK per-account with reservation (slots + budgets) |
| 38943 | read_only | requested_aid = payload.get("account_id") |
| 38955 | read_only | eq0 = float((st0 or {}).get("equity_usd", 0.0) or 0.0) |
| 38956 | read_only | used0 = float((st0 or {}).get("total_used_usd", 0.0) or 0.0) + float((st0 or {}).get("planned_total_usd", 0.0) or 0.0) |
| 38958 | write_metric | existing_syms0 = set((st0 or {}).get("existing_symbols") or set()) |
| 38959 | write_metric | planned_syms0 = set((st0 or {}).get("planned_symbols") or set()) |
| 38960 | read_only | max_syms0 = int((st0 or {}).get("max_symbols") or 5) |
| 38970 | write_metric | enabled_accounts = set((ACTIVE_TRADING_ACCOUNTS or TRADING_ACCOUNTS or [])) |
| 38972 | write_metric | enabled_accounts = set(TRADING_ACCOUNTS or []) |
| 38974 | write_metric | any_published = False |
| 38980 | write_metric | logged = getattr(self, "_logged_account_disabled", set()) |
| 38989 | read_only | st = open_risk_governor.get(aid) or {} |
| 38990 | read_only | eq = float(st.get("equity_usd", 0.0) or 0.0) |
| 38992 | write_signal | # This enables pipeline validation with unfunded accounts (signals publish but |
| 39005 | read_only | _rc_fb = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 39008 | read_only | _raw_eq_fb = _rc_fb.get(f"portfolio:equity:{aid}") |
| 39017 | read_only | _fb_eq = float(_eq_data.get("equity", 0) or _eq_data.get("equity_usd", 0) or _eq_data.get("margin_balance", 0) or 0) |
| 39018 | read_only | _fb_ts = int(_eq_data.get("ts_ms", 0) or _eq_data.get("timestamp", 0) or 0) |
| 39047 | write_metric | from utils.ensemble_diagnostics import publish_ensemble_diagnostic |
| 39048 | read_only | did = payload.get("decision_id") or f"{int(time.time()*1000)}-{symbol}-{payload.get('timeframe') or payload.get('tf') or 'na'}-{aid}" |
| 39049 | write_metric | publish_ensemble_diagnostic({ |
| 39053 | read_only | "tf": payload.get("timeframe") or payload.get("tf") or "na", |
| 39055 | read_only | "base_action": payload.get("action") or payload.get("action_name"), |
| 39056 | read_only | "final_action": payload.get("final_action") or payload.get("action_name") or payload.get("action"), |
| 39057 | read_only | "confidence": float(payload.get("confidence") or payload.get("model_confidence") or 0.0), |
| 39068 | write_signal | # Prevent recursive multi-account broadcasting inside _publish_signal_payload. |
| 39085 | read_only | used_now = float(st.get("total_used_usd", 0.0) or 0.0) + float(st.get("planned_total_usd", 0.0) or 0.0) |
| 39087 | read_only | conf0 = float(p2.get("confidence") or p2.get("model_confidence") or 0.0) |
| 39090 | read_only | tox0 = float(p2.get("toxicity", 0.0) or 0.0) |
| 39103 | read_only | if self._signal_redis: |
| 39104 | read_only | pb_raw = self._signal_redis.get(f"profit_bank:state:{aid}") |
| 39108 | read_only | bank_usd = float(pb.get("balance_usd", 0.0) or 0.0) |
| 39128 | read_only | cur_margin2 = float(p2.get("margin_usd", 0.0) or 0.0) |
| 39149 | read_only | lev0 = float(p2.get("leverage") or 1.0) |
| 39156 | read_only | p2["position_size_pct"] = (float(up) / float(eq) * 100.0) if eq > 0 else float(p2.get("position_size_pct") or 0.0) |
| 39170 | read_only | p2["notional_usd"] = float(p2.get("notional_usd", 0.0) or 0.0) * float(scale2) |
| 39174 | read_only | p2["position_size_pct"] = float(p2.get("position_size_pct", 0.0) or 0.0) * float(scale2) |
| 39186 | read_only | act_u = str(p2.get("action_name") or p2.get("action") or "").upper() |
| 39190 | read_only | cat_u = str(p2.get("action_category") or "").upper() |
| 39193 | read_only | is_hedge_action = bool(p2.get("hedge_intent")) or (cat_u == "HEDGE") or act_u.startswith(("OPEN_HEDGE_", "ADD_HEDGE_")) |
| 39199 | read_only | _dlg_redis = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 39200 | read_only | if _dlg_redis: |
| 39202 | read_only | _dlg_raw = _dlg_redis.hgetall(_dlg_pos_key) |
| 39213 | read_only | _dside = str(_dpos.get("side") or _dpos.get("positionSide") or "").upper() |
| 39214 | read_only | _dsize = abs(float(_dpos.get("size") or _dpos.get("positionAmt") or 0)) |
| 39236 | write_signal | built = self._publish_signal_payload(p2, contract_required=True) |
| 39238 | write_metric | logger.error(f"[PUBLISH_BUFFERED][JAN6][HEDGE_BYPASS] EXCEPTION: {symbol} {act_u} account={aid} - {pub_err}") |
| 39241 | write_metric | any_published = True |
| 39242 | write_metric | published_count += 1 |
| 39244 | write_risk_state | # WHY_NO_OPEN_RISK: mark OPEN_RISK published (deconfliction path) |
| 39247 | read_only | act0 = str(built.get("action_name") or built.get("action") or p2.get("action_name") or p2.get("action") or "") |
| 39249 | write_risk_state | self._why_no_open_risk_mark_published(str(symbol)) |
| 39254 | write_metric | blocked_reasons_by_account[str(aid)] = "HEDGE_PUBLISH_NONE" |
| 39258 | read_only | margin_req = float(p2.get("margin_usd", 0.0) or 0.0) |
| 39263 | write_metric | self._publish_skip_event(p2, "PORTFOLIO_BUDGET_BLOCK", f"missing sizing for governor (side={side} margin_usd={margin_req})") |
| 39272 | write_metric | existing_syms = set(st.get("existing_symbols") or set()) |
| 39273 | write_metric | planned_syms = set(st.get("planned_symbols") or set()) |
| 39277 | read_only | max_syms = int(st.get("max_symbols") or int(PORTFOLIO_BASE_MAX_POSITIONS)) |
| 39279 | read_only | max_syms = int(st.get("max_symbols") or 10) |
| 39288 | read_only | if self._signal_redis: |
| 39289 | read_only | _sc_raw = self._signal_redis.get(f"regime:{symbol}") |
| 39292 | read_only | _sc_m = str(_sc_d.get("move_regime", "")).upper() |
| 39293 | read_only | _sc_v = float(_sc_d.get("volatility_score", 0.5) or 0.5) |
| 39294 | read_only | _sc_a = abs(float(_sc_d.get("tf_alignment", 0) or 0)) |
| 39307 | read_only | if self._signal_redis: |
| 39308 | read_only | _rr = self._signal_redis.get(f"regime:{symbol}") |
| 39313 | read_only | _slot_trend = str(_slot_regime.get("trend_direction", "")).upper() |
| 39314 | read_only | _slot_move = str(_slot_regime.get("move_regime", "")).upper() |
| 39330 | write_metric | self._publish_skip_event( |
| 39361 | read_only | regime = str(reg.get("regime") or reg.get("market_regime") or "").upper() |
| 39366 | read_only | td = str(reg.get("trend_direction") or reg.get("trend_dir") or "").upper() |
| 39377 | read_only | for sym0, pd0 in (st.get("positions") or {}).items(): |
| 39380 | read_only | sd = str(pd0.get("side") or "").upper() |
| 39410 | write_signal | built_fs = self._publish_signal_payload(free_sig, contract_required=True) |
| 39412 | write_metric | logger.info(f"[FREESPACE] Published {cand.symbol} {act_close} close_pct={cand.close_pct*100:.1f}% net=${cand.est_net_profit_usd:.2f} / {cand.reason}") |
| 39422 | read_only | is_hedge_action = bool(p2.get("hedge_intent")) or (p2.get("action_category") == "HEDGE") or ("HEDGE" in act_u) |
| 39424 | write_metric | # Hedges bypass budget caps - proceed directly to publish |
| 39426 | write_metric | # Fall through to publish without budget checks |
| 39429 | write_signal | built = self._publish_signal_payload(p2, contract_required=True) |
| 39431 | write_metric | logger.error(f"[PUBLISH_BUFFERED][HEDGE_BYPASS] EXCEPTION: {symbol} {act_u} account={aid} - {pub_err}") |
| 39434 | write_metric | any_published = True |
| 39435 | write_metric | published_count += 1 |
| 39437 | write_risk_state | # WHY_NO_OPEN_RISK: mark OPEN_RISK published (deconfliction path) |
| 39440 | read_only | act0 = str(built.get("action_name") or built.get("action") or p2.get("action_name") or p2.get("action") or "") |
| 39442 | write_risk_state | self._why_no_open_risk_mark_published(str(symbol)) |
| 39446 | write_signal | self._signal_redis.hset( |
| 39452 | read_only | agg_key = p2.get('_aggregation_key') |
| 39456 | write_metric | self._last_published_ts[agg_key] = now_ms |
| 39460 | read_only | conf_f = float(p2.get("confidence") or p2.get("model_confidence") or 0.0) |
| 39465 | read_only | fastlane_hint = bool(p2.get("fastlane")) or bool(p2.get("is_flash_move")) or float(p2.get("flash_move_pct", 0.0) or 0.0) != 0.0 |
| 39479 | write_metric | existing_groups = set(st.get("existing_groups") or set()) |
| 39480 | write_metric | planned_groups = set(st.get("planned_groups") or set()) |
| 39484 | read_only | total_used_est = float(st.get("total_used_usd", 0.0) or 0.0) + float(st.get("planned_total_usd", 0.0) or 0.0) |
| 39493 | write_metric | self._publish_skip_event( |
| 39501 | read_only | group_members = list(_corr_groups.get(g) or []) |
| 39502 | write_metric | self._maybe_publish_recovery_reduction( |
| 39511 | read_only | positions_hint=(st.get("positions") if isinstance(st, dict) else None), |
| 39524 | read_only | long_used = float(st.get("long_used_usd", 0.0) or 0.0) + float(st.get("planned_long_usd", 0.0) or 0.0) |
| 39525 | read_only | short_used = float(st.get("short_used_usd", 0.0) or 0.0) + float(st.get("planned_short_usd", 0.0) or 0.0) |
| 39526 | read_only | total_used = float(st.get("total_used_usd", 0.0) or 0.0) + float(st.get("planned_total_usd", 0.0) or 0.0) |
| 39530 | read_only | max_long_slots = int(st.get("max_long_slots") or st.get("max_symbols") or 10) |
| 39532 | read_only | max_long_slots = int(st.get("max_symbols") or 10) |
| 39534 | read_only | max_short_slots = int(st.get("max_short_slots") or st.get("max_symbols") or 10) |
| 39536 | read_only | max_short_slots = int(st.get("max_symbols") or 10) |
| 39538 | write_metric | published_count_local = int(st.get("published_count") or 0) |
| 39540 | write_metric | published_count_local = 0 |
| 39542 | read_only | long_slots_used = int(st.get("long_slots_used") or 0) |
| 39543 | write_metric | if published_count_local > 0: |
| 39544 | read_only | long_slots_used += int(st.get("planned_long_slots") or 0) |
| 39546 | read_only | long_slots_used = int(st.get("planned_long_slots") or 0) |
| 39548 | read_only | short_slots_used = int(st.get("short_slots_used") or 0) |
| 39549 | write_metric | if published_count_local > 0: |
| 39550 | read_only | short_slots_used += int(st.get("planned_short_slots") or 0) |
| 39552 | read_only | short_slots_used = int(st.get("planned_short_slots") or 0) |
| 39568 | read_only | if self._signal_redis: |
| 39569 | read_only | _ss_rr = self._signal_redis.get(f"regime:{symbol}") |
| 39574 | read_only | _ss_trend = str(_ss_regime.get("trend_direction", "")).upper() |
| 39575 | read_only | _ss_move = str(_ss_regime.get("move_regime", "")).upper() |
| 39589 | write_metric | existing_syms = set(st.get("existing_symbols") or set()) |
| 39590 | write_metric | planned_syms = set(st.get("planned_symbols") or set()) |
| 39591 | read_only | position_count = st.get("position_count") |
| 39592 | read_only | positions = st.get("positions") |
| 39594 | write_signal | "[SLOT_BLOCK] aid=%s side=%s slots=%s/%s used_slots=%s published=%s long_used=%.2f short_used=%.2f " |
| 39601 | write_metric | int(st.get("published_count") or 0), |
| 39610 | write_metric | self._publish_skip_event( |
| 39627 | read_only | if cycle_id and st.get(log_key) != cycle_id: |
| 39628 | write_metric | existing_syms = set(st.get("existing_symbols") or set()) |
| 39629 | write_metric | planned_syms = set(st.get("planned_symbols") or set()) |
| 39671 | read_only | lev0 = float(p2.get("leverage") or 1.0) |
| 39676 | read_only | p2["notional_usd"] = float(p2.get("margin_usd", 0.0) or 0.0) * float(lev0) |
| 39678 | read_only | p2["position_size_pct"] = (float(p2.get("margin_usd", 0.0) or 0.0) / float(eq) * 100.0) if eq > 0 else float(p2.get("position_size_pct") or 0.0) |
| 39681 | read_only | margin_req = float(p2.get("margin_usd", 0.0) or 0.0) |
| 39683 | write_metric | self._publish_skip_event( |
| 39698 | write_metric | self._publish_skip_event( |
| 39705 | write_metric | self._maybe_publish_recovery_reduction( |
| 39713 | read_only | positions_hint=(st.get("positions") if isinstance(st, dict) else None), |
| 39740 | read_only | lev0 = float(p2.get("leverage") or 1.0) |
| 39745 | read_only | p2["notional_usd"] = float(p2.get("margin_usd", 0.0) or 0.0) * float(lev0) |
| 39747 | read_only | p2["position_size_pct"] = (float(p2.get("margin_usd", 0.0) or 0.0) / float(eq) * 100.0) if eq > 0 else float(p2.get("position_size_pct") or 0.0) |
| 39750 | read_only | margin_req = float(p2.get("margin_usd", 0.0) or 0.0) |
| 39758 | write_metric | self._publish_skip_event( |
| 39765 | write_metric | self._maybe_publish_recovery_reduction( |
| 39773 | read_only | positions_hint=(st.get("positions") if isinstance(st, dict) else None), |
| 39784 | write_metric | # Publish (per-account) |
| 39792 | read_only | _htf_bias = int(p2.get("tf_bias_dir") or p2.get("mtf_structural_bias_dir") or 0) |
| 39794 | read_only | # Try reading 4h bias from Redis tf_votes |
| 39795 | read_only | _tv = p2.get("tf_votes") or {} |
| 39799 | read_only | _htf_bias = int(float(_tv.get("4h", 0) or 0)) |
| 39807 | write_metric | self._publish_skip_event( |
| 39822 | write_metric | # CRITICAL (Jan 2026): When ORCHESTRATOR_WORKER_MODE=publish, use _emit_proposal() |
| 39823 | write_signal | # instead of _publish_signal_payload() to route through orchestrator worker. |
| 39830 | write_metric | str(ORCHESTRATOR_WORKER_MODE).lower() == "publish" |
| 39852 | write_metric | # Legacy path: direct publish (only when orchestrator disabled/shadow) |
| 39853 | write_signal | built = self._publish_signal_payload(p2, contract_required=True) |
| 39855 | write_metric | logger.error(f"[PUBLISH_BUFFERED][JAN6] EXCEPTION: {symbol} {act_u} account={aid} - {pub_err}") |
| 39859 | write_metric | any_published = True |
| 39860 | write_metric | published_count += 1 |
| 39863 | write_metric | st["published_count"] = int(st.get("published_count") or 0) + 1 |
| 39866 | write_risk_state | # WHY_NO_OPEN_RISK: mark OPEN_RISK published (deconfliction path) |
| 39869 | read_only | act0 = str(built.get("action_name") or built.get("action") or p2.get("action_name") or p2.get("action") or "") |
| 39871 | write_risk_state | self._why_no_open_risk_mark_published(str(symbol)) |
| 39877 | write_signal | self._signal_redis.hset( |
| 39884 | write_metric | # Update duplicate suppression timestamp AFTER successful publish |
| 39885 | read_only | agg_key = p2.get('_aggregation_key') |
| 39889 | write_metric | self._last_published_ts[agg_key] = now_ms |
| 39891 | write_risk_state | # Update churn cooldown timestamp AFTER successful publish |
| 39893 | read_only | _cd_redis = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 39894 | read_only | if _cd_redis and symbol: |
| 39896 | write_metric | _cd_redis.setex(f"trainer:deconflict:last_publish:{symbol}", _cd_ttl, str(int(time.time() * 1000))) |
| 39900 | write_metric | # Reserve symbol + budget for remainder of this publish cycle |
| 39912 | read_only | st["planned_long_slots"] = int(st.get("planned_long_slots") or 0) + 1 |
| 39914 | read_only | st["planned_short_slots"] = int(st.get("planned_short_slots") or 0) + 1 |
| 39917 | read_only | st["planned_total_usd"] = float(st.get("planned_total_usd", 0.0) or 0.0) + float(margin_req) |
| 39919 | read_only | st["planned_long_usd"] = float(st.get("planned_long_usd", 0.0) or 0.0) + float(margin_req) |
| 39921 | read_only | st["planned_short_usd"] = float(st.get("planned_short_usd", 0.0) or 0.0) + float(margin_req) |
| 39926 | write_signal | blocked_reasons_by_account.setdefault(str(aid), "PUBLISH_PAYLOAD_NONE (see signals:execution:skips)") |
| 39929 | write_metric | if not any_published: |
| 39931 | write_signal | f"[PUBLISH_BUFFERED][JAN6] OPEN_RISK blocked on all accounts: {symbol} {action_name} / " |
| 39946 | write_metric | logger.warning(f"[PUBLISH_BUFFERED][JAN6] Governor failed (fallback to legacy): {gov_err}") |
| 39954 | read_only | self._margin_metrics.get('available_balance', 0) |
| 39955 | read_only | or self._margin_metrics.get('total_margin_balance', 0) |
| 39956 | read_only | or self._margin_metrics.get('total_wallet_balance', 0) |
| 39968 | write_checkpoint_metadata | logger.warning(f"[PUBLISH_BUFFERED] {symbol}: ppo_model not available, using raw payload") |
| 39971 | write_signal | logger.warning(f"[PUBLISH_BUFFERED] {symbol} {action_name}: _build_trade_signal returned None (sizing blocked)") |
| 39977 | read_only | action_name = payload.get('action_name', action_name) |
| 39979 | read_only | conf = float(payload.get('confidence') or payload.get('model_confidence', 0) or 0) |
| 39985 | write_signal | # This MUST happen after action normalization but before publishing |
| 39989 | read_only | action_name = payload.get('action_name', action_name)  # Update if changed |
| 39993 | write_metric | # AUDIT: Log what we're attempting to publish |
| 39995 | read_only | margin_usd = float(payload.get('margin_usd', 0) or 0) |
| 39999 | read_only | notional_usd = float(payload.get('notional_usd', 0) or 0) |
| 40003 | read_only | leverage = int(float(payload.get('leverage') or payload.get('recommended_leverage', 0) or 0)) |
| 40006 | write_signal | logger.info(f"[PUBLISH_BUFFERED] Attempting: {symbol} {action_name} margin=${margin_usd:.2f} notional=${notional_usd:.2f} lev={leverage} conf={conf:.3f} builder={payload.get('builder_version')}") |
| 40011 | write_risk_state | # Publish OPEN_RISK only if it does not impair hedge feasibility. |
| 40018 | read_only | cat_u = str(payload.get("action_category") or _get_cat(str(action_name or ""))).upper() |
| 40022 | read_only | aid_u = str(payload.get("account_id") or payload.get("account") or "primary").strip().lower() |
| 40026 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 40031 | read_only | raw = rc.get(f"portfolio:equity:{aid}") if rc else None |
| 40036 | read_only | util = float(j.get("margin_utilization_pct", 0.0) or 0.0) |
| 40037 | read_only | avail = j.get("available_margin_usd") or j.get("available_usd") or j.get("available_balance") or j.get("available") or 0.0 |
| 40054 | read_only | (str(p.get("action_category") or _get_cat(str(p.get("action_name") or p.get("action") or ""))).upper() == "HEDGE") |
| 40055 | read_only | or bool(p.get("hedge_intent")) |
| 40056 | read_only | or str(p.get("action_name") or "").upper().startswith(("OPEN_HEDGE_", "ADD_HEDGE_")) |
| 40062 | read_only | req_m = float(payload.get("margin_usd", 0.0) or 0.0) |
| 40067 | read_only | nn = float(payload.get("notional_usd", 0.0) or 0.0) |
| 40071 | read_only | lv = float(payload.get("leverage", payload.get("recommended_leverage", 10)) or 10.0) |
| 40079 | write_metric | self._publish_skip_event( |
| 40091 | write_metric | # IMPORTANT: In ORCHESTRATOR_WORKER_MODE=publish, direct publish is forbidden. |
| 40092 | write_metric | # Route through unified publisher which emits proposals to `wma:proposals`. |
| 40093 | write_signal | built = self._publish_signal_unified(payload, contract_required=True) |
| 40095 | write_signal | logger.error(f"[PUBLISH_BUFFERED] EXCEPTION: {symbol} {action_name} - {pub_err}") |
| 40100 | write_signal | self._signal_redis.hset( |
| 40105 | write_metric | logger.debug(f"[PUBLISH_BUFFERED] failed to update last hash for {symbol}") |
| 40107 | write_metric | published_count += 1 |
| 40109 | write_metric | # Update duplicate suppression timestamp AFTER successful publish |
| 40110 | read_only | agg_key = payload.get('_aggregation_key') |
| 40114 | write_metric | self._last_published_ts[agg_key] = now_ms |
| 40117 | write_risk_state | # Update churn cooldown timestamp AFTER successful publish (legacy path) |
| 40119 | read_only | _cd_redis2 = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 40120 | read_only | if _cd_redis2 and symbol: |
| 40126 | write_metric | _cd_redis2.setex(f"trainer:deconflict:last_publish:{symbol}", _cd_ttl2, str(int(time.time() * 1000))) |
| 40136 | read_only | market_regime_info = payload.get('market_regime') or payload.get('market_regime_info') |
| 40142 | read_only | timeframe=payload.get('timeframe', 'multi'), |
| 40154 | write_signal | logger.warning(f"[PUBLISH_BUFFERED] BLOCKED: {symbol} {action_name} - _publish_signal_payload returned None (check skip events)") |
| 40157 | write_signal | logger.warning(f"⛔ [PUBLISH_BUFFERED] blocked={blocked_count}/{len(payloads)} (see signals:execution:skips)") |
| 40159 | write_signal | logger.info(f"✅ Published {published_count} deconflicted signals to Redis") |
| 40161 | write_signal | # Record published predictions for accuracy tracking |
| 40168 | write_signal | # Periodically evaluate prediction accuracy (every ~10 publish cycles) |
| 40178 | write_signal | logger.exception(f"❌ Failed to publish buffered signals: {e}") |
| 40181 | write_metric | return published_count |
| 40241 | read_only | """Build deterministic Redis-hash field ordering for vectorization. |
| 40243 | read_only | Redis hashes are unordered; relying on `.items()` produces nondeterministic vectors. |
| 40262 | write_metric | keys_set = set() |
| 40316 | read_only | Production TA Section 3: Convert Redis feature dicts to GPU tensor in one shot |
| 40321 | read_only | feature_dicts: List of decoded Redis feature hashes |
| 40383 | read_only | per_sym_order = self._per_sym_key_order_cache.get(_per_sym_cache_key) |
| 40389 | read_only | if os.path.exists(_pin_path): |
| 40403 | write_metric | keys_set = set() |
| 40410 | read_only | "[PER_SYM_KEYORDER] Built from Redis for %s:%s keys=%d (after TA pruning)", |
| 40425 | read_only | vv = fdict.get(kk) |
| 40578 | write_signal | # (We will make snapshot creation more robust so this does not deadlock signal publishing.) |
| 40585 | write_metric | return bool(evt is not None and evt.is_set()) |
| 40916 | write_metric | _n_unique = len(set(_row_hashes)) |
| 40933 | write_metric | _n_uniq_post = len(set(_hashes_post)) |
| 41003 | read_only | _pos_enc = float((feature_dicts[_mi] or {}).get("position_side_encoding", "0") or 0.0) |
| 41165 | write_signal | # BETTER learning → LOWER confidence → signals never published. |
| 41201 | read_only | _policy_kl = float(_ds.get('policy_kl', 0.0) or 0.0) |
| 41732 | read_only | logger.info(f"[GPU_BATCH] MoE applied (entropy-penalized): top_experts={_moe_diag.get('top_expert_distribution', {})}") |
| 41841 | read_only | if not drift_result.get("skipped") and drift_result.get("alerts"): |
| 41863 | read_only | _pchg = float(_fd.get("ccxt_price_change_5m_pct", 0) or 0) |
| 41866 | read_only | _mom_thr = _mom_tf_thresholds.get(_tf_i, 0.03) |
| 41867 | read_only | _mom_mul = _mom_tf_mult.get(_tf_i, 7) |
| 41952 | read_only | _sym = str(_fd.get('symbol', symbols[_li] if _li < len(symbols) else '')) |
| 41953 | read_only | _tf = str(_fd.get('timeframe', timeframes[_li] if _li < len(timeframes) else '')) |
| 42081 | write_signal | # When 0 OPEN_RISK signals published for N consecutive cycles, |
| 42119 | read_only | acct_ctx = str((feature_dicts[i] or {}).get("_acct_for_ctx", "primary")).strip().lower() |
| 42120 | read_only | pos_enc = float((feature_dicts[i] or {}).get("position_side_encoding", "0") or 0.0) |
| 42139 | read_only | _pl = self._real_positions.get(f"{symbol_i}:LONG") or self._real_positions.get(f"{symbol_i}_LONG") |
| 42140 | read_only | _ps = self._real_positions.get(f"{symbol_i}:SHORT") or self._real_positions.get(f"{symbol_i}_SHORT") |
| 42141 | read_only | _pb = self._real_positions.get(symbol_i)  # bare key fallback |
| 42143 | read_only | if _pl and abs(float(_pl.get('size', 0) or _pl.get('positionAmt', 0) or 0)) > 0: |
| 42146 | read_only | position_pnl_pct = float(_pl.get('pnl_percentage', 0) or _pl.get('pnl_pct', 0) or _pl.get('roi_pct', 0) or 0) |
| 42147 | read_only | if _ps and abs(float(_ps.get('size', 0) or _ps.get('positionAmt', 0) or 0)) > 0: |
| 42151 | read_only | position_pnl_pct = float(_ps.get('pnl_percentage', 0) or _ps.get('pnl_pct', 0) or _ps.get('roi_pct', 0) or 0) |
| 42154 | read_only | _b_size = abs(float(_pb.get('size', 0) or _pb.get('positionAmt', 0) or 0)) |
| 42157 | read_only | _b_side = str(_pb.get('side', '')).upper() |
| 42162 | read_only | position_pnl_pct = float(_pb.get('pnl_percentage', 0) or _pb.get('pnl_pct', 0) or _pb.get('roi_pct', 0) or 0) |
| 42245 | read_only | _sr = self._signal_redis if hasattr(self, '_signal_redis') and self._signal_redis else None |
| 42247 | read_only | _reg_raw = _sr.get(f"regime:{symbol_i}") |
| 42321 | read_only | _uc_action_name = str(_AID2NAME_UC.get(_uc_action_idx, "HOLD")).upper() |
| 42343 | read_only | _uc_price_raw = self._signal_redis.get(f"price:{symbols[i]}") |
| 42348 | read_only | _uc_cpx = float(json.loads(_pr_str).get("price", 0) or 0) |
| 42353 | read_only | _natr_val = _lookup_natr_atr_pct(self._signal_redis, symbols[i]) |
| 42358 | read_only | _uf = self._signal_redis.hgetall(f"unified_features:{symbols[i]}:{timeframes[i]}") |
| 42360 | read_only | _uc_atr = max(float(_uf.get("ccxt_atr14_pct", 0) or 0), 0.002) or 0.01 |
| 42382 | write_metric | "published": "0", |
| 42387 | write_signal | self._signal_redis.hset(_uc_key, mapping=_uc_map) |
| 42388 | read_only | self._signal_redis.expire(_uc_key, 1800) |
| 42392 | write_signal | # C.3) Debug Stream Publishing - Publish filtered signals with reason codes |
| 42421 | read_only | _dec_act_name = str(_AID2NAME_DEC.get(_dec_idx, "HOLD")).upper() |
| 42430 | read_only | _dec_rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 42438 | read_only | _dec_mtf["tf_conflict_score"] = float(_dec_a.get("conflict_score", 0.0) or 0.0) |
| 42439 | read_only | _dec_mtf["tf_bias_dir"] = int(_dec_a.get("bias_dir", 0) or 0) |
| 42440 | read_only | _dec_mtf["tf_timing_dir"] = int(_dec_a.get("timing_dir", 0) or 0) |
| 42441 | read_only | _dec_votes = _dec_a.get("tf_votes") or {} |
| 42470 | write_metric | "published": 0, |
| 42479 | read_only | flat_primary_block_reasons["LOW_CONF"] = flat_primary_block_reasons.get("LOW_CONF", 0) + 1 |
| 42481 | write_metric | # C.3) Publish to debug stream |
| 42497 | write_signal | self._signal_redis.xadd('signals:debug', debug_payload, maxlen=5000) |
| 42498 | write_signal | logger.debug(f"[DEBUG-STREAM] Published filtered signal: {symbols[i]}:{timeframes[i]} - {filtered_reason}") |
| 42500 | write_signal | logger.debug(f"[DEBUG-STREAM] Failed to publish filtered signal: {e}") |
| 42504 | write_signal | # ── Trainer Intent: publish even for confidence-filtered signals ── |
| 42509 | write_signal | from risk.trainer_intent import publish_intent, infer_direction_from_action |
| 42514 | read_only | _filt_action_name = str(_AID2NAME_INT.get(_filt_action_idx, "HOLD")).upper() |
| 42518 | write_metric | publish_intent( |
| 42519 | read_only | self._signal_redis, |
| 42537 | read_only | _da_name = str(_DA2N.get(_uc_idx, "HOLD")).upper() |
| 42580 | read_only | flat_primary_block_reasons["COOLDOWN"] = flat_primary_block_reasons.get("COOLDOWN", 0) + 1 |
| 42582 | write_metric | # Publish to debug stream |
| 42595 | write_signal | self._signal_redis.xadd('signals:debug', debug_payload, maxlen=5000) |
| 42610 | read_only | raw_action_name = str(_AID2NAME.get(predicted_action_idx, "HOLD")).upper() |
| 42620 | read_only | last_ts = float(self._ppo_policy_debug_last_ts.get(dbg_key, 0.0) or 0.0) |
| 42700 | read_only | flat_primary_block_reasons["TOP_PROB_GATE"] = flat_primary_block_reasons.get("TOP_PROB_GATE", 0) + 1 |
| 42706 | read_only | flat_primary_action_pre[predicted_action] = flat_primary_action_pre.get(predicted_action, 0) + 1 |
| 42737 | read_only | _pos_long = self._real_positions.get(f"{symbols[i]}:LONG", {}) or {} |
| 42738 | read_only | _pos_short = self._real_positions.get(f"{symbols[i]}:SHORT", {}) or {} |
| 42740 | read_only | _pos_bare = self._real_positions.get(symbols[i], {}) or {} |
| 42742 | read_only | long_qty = abs(float(_pos_long.get("size", 0) or _pos_long.get("positionAmt", 0) or 0.0)) |
| 42743 | read_only | short_qty = abs(float(_pos_short.get("size", 0) or _pos_short.get("positionAmt", 0) or 0.0)) |
| 42747 | read_only | _bare_size = abs(float(_pos_bare.get("size", 0) or _pos_bare.get("positionAmt", 0) or 0.0)) |
| 42748 | read_only | _bare_side = str(_pos_bare.get("side") or "").upper() |
| 42790 | read_only | if rev.get("active") and "OPEN_SHORT" in str(predicted_action or ""): |
| 42797 | read_only | rev.get("until_ms"), |
| 42849 | read_only | flat_primary_action_post[predicted_action] = flat_primary_action_post.get(predicted_action, 0) + 1 |
| 42873 | read_only | acct_ctx = str((feature_dicts[i] or {}).get("_acct_for_ctx", "primary")).strip().lower() |
| 42918 | read_only | _price_chg_5m = float((feature_dicts[i] or {}).get("ccxt_price_change_5m_pct", "0") or 0.0) |
| 42950 | read_only | position = self._real_positions.get(symbols[i], {}) |
| 42957 | read_only | margin_util = self._margin_metrics.get('margin_utilization', 0.0) |
| 42979 | read_only | gate_meta = dict(self._last_liquidity_gate_result.get(symbols[i], {}) or {}) |
| 42987 | read_only | gate_meta.get("spread_pct"), |
| 42988 | read_only | gate_meta.get("depth_usd"), |
| 42991 | write_metric | self._publish_exec_event( |
| 43000 | read_only | "spread_pct": gate_meta.get("spread_pct"), |
| 43001 | read_only | "depth_usd": gate_meta.get("depth_usd"), |
| 43002 | read_only | "orderbook_ts_ms": gate_meta.get("orderbook_ts_ms"), |
| 43032 | read_only | "spread_pct": gate_meta.get("spread_pct"), |
| 43033 | read_only | "depth_usd": gate_meta.get("depth_usd"), |
| 43062 | read_only | flat_primary_block_reasons[key] = flat_primary_block_reasons.get(key, 0) + 1 |
| 43063 | write_metric | # Publish to debug stream |
| 43076 | write_signal | self._signal_redis.xadd('signals:debug', debug_payload, maxlen=5000) |
| 43091 | read_only | flat_primary_block_reasons[mask_reason] = flat_primary_block_reasons.get(mask_reason, 0) + 1 |
| 43093 | write_metric | self._publish_exec_event( |
| 43100 | read_only | "direction": axes.get("direction"), |
| 43101 | read_only | "structure": axes.get("structure"), |
| 43102 | read_only | "stress": axes.get("stress"), |
| 43124 | read_only | _batch_rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 43138 | read_only | _batch_liq_long_str = float((_batch_fd.get("liquidation_long_strength") or 0.0)) |
| 43139 | read_only | _batch_liq_short_str = float((_batch_fd.get("liquidation_short_strength") or 0.0)) |
| 43140 | read_only | # Fallback: read directly from Redis if feature dict lacks liq fields |
| 43144 | read_only | _liq_rd_b = getattr(self, "redis", None) or getattr(self, "_signal_redis", None) |
| 43146 | read_only | _liq_data_b = _liq_rd_b.hgetall(_liq_key_b) |
| 43148 | read_only | _batch_liq_long_str = float((_liq_data_b.get("liquidation_long_strength") or _liq_data_b.get(b"liquidation_long_strength") or 0.0)) |
| 43149 | read_only | _batch_liq_short_str = float((_liq_data_b.get("liquidation_short_strength") or _liq_data_b.get(b"liquidation_short_strength") or 0.0)) |
| 43162 | read_only | _tf_votes = _batch_tf_agg.get("tf_votes", {}) |
| 43163 | read_only | _tf_bias = int(_batch_tf_agg.get("bias_dir", 0) or 0) |
| 43164 | read_only | _tf_timing = int(_batch_tf_agg.get("timing_dir", 0) or 0) |
| 43171 | read_only | if _tf_bias == 0 and _tf_timing == 0 and float(_batch_tf_agg.get("conflict_score", 0.0) or 0.0) <= 0.0: |
| 43207 | read_only | _tf_votes_cg = _batch_tf_agg.get("tf_votes", {}) |
| 43208 | read_only | _bias_dir_cg = int(_batch_tf_agg.get("bias_dir", 0) or 0) |
| 43209 | read_only | _ta_strength_cg = float(_batch_tf_agg.get("ta_strength", 0.0) or 0.0) |
| 43263 | read_only | from risk.market_regime import compute_regime_from_redis |
| 43264 | read_only | _regime_redis = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 43269 | read_only | (feature_dicts[i] if feature_dicts and i < len(feature_dicts) else {}).get("leverage") |
| 43277 | read_only | _batch_regime = compute_regime_from_redis( |
| 43278 | read_only | _regime_redis, |
| 43307 | read_only | 'model_action_name': str(_AID2NAME.get(predicted_action_idx, 'UNKNOWN')).upper(), |
| 43322 | read_only | 'regime_direction': (self._last_regime_axes.get(symbols[i], {}) or {}).get("direction"), |
| 43323 | read_only | 'regime_structure': (self._last_regime_axes.get(symbols[i], {}) or {}).get("structure"), |
| 43324 | read_only | 'regime_stress': (self._last_regime_axes.get(symbols[i], {}) or {}).get("stress"), |
| 43326 | read_only | 'tf_bias_dir': int(_batch_tf_agg.get("bias_dir", 0) or 0), |
| 43327 | read_only | 'tf_timing_dir': int(_batch_tf_agg.get("timing_dir", 0) or 0), |
| 43328 | read_only | 'tf_conflict_score': float(_batch_tf_agg.get("conflict_score", 0.0) or 0.0), |
| 43329 | read_only | 'tf_votes': _batch_tf_agg.get("tf_votes", {}), |
| 43330 | read_only | 'bias_dir': int(_batch_tf_agg.get("bias_dir", 0) or 0), |
| 43331 | read_only | 'timing_dir': int(_batch_tf_agg.get("timing_dir", 0) or 0), |
| 43332 | read_only | 'conflict_score': float(_batch_tf_agg.get("conflict_score", 0.0) or 0.0), |
| 43337 | read_only | 'move_score': float(_batch_regime.get("move_score", 0.0)), |
| 43338 | read_only | 'move_regime': _batch_regime.get("move_regime") or None, |
| 43339 | read_only | 'market_regime': _batch_regime.get("move_regime") or None, |
| 43340 | read_only | 'trend_direction': _batch_regime.get("trend_direction") or None, |
| 43341 | read_only | 'tf_alignment': float(_batch_regime.get("tf_alignment", 0.0) or 0.0), |
| 43342 | read_only | 'volatility_score': float(_batch_regime.get("volatility_score", 0.0)), |
| 43343 | read_only | 'fast_move_score': float(_batch_regime.get("fast_move_score", 0.0)), |
| 43344 | read_only | 'liq_risk': float(_batch_regime.get("liq_risk", 0.0)), |
| 43345 | read_only | 'liquidity_score': float(_batch_regime.get("liquidity_score", 0.0)), |
| 43373 | read_only | prediction['moe_expert_weights'] = _moe_diag.get('expert_weights_mean', []) |
| 43378 | read_only | prediction['drift_feature_psi'] = drift_summary.get('feature_psi', 0.0) |
| 43379 | read_only | prediction['drift_policy_kl'] = drift_summary.get('policy_kl', 0.0) |
| 43441 | read_only | _v2_tf_votes = prediction.get("tf_votes", {}) |
| 43447 | read_only | _v2_redis = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 43449 | read_only | if _v2_redis and _v2_is_entry: |
| 43453 | read_only | _v2_redis, symbols[i], _v2_dir, _v2_source_tf |
| 43461 | read_only | elif _v2_dir and not check_regime_gate(_v2_redis, symbols[i], _v2_dir, confidence=float(prediction.get("confidence", 0.0))): |
| 43468 | read_only | if _v2_redis: |
| 43470 | read_only | if not check_signal_emit_cadence(_v2_redis, symbols[i], _v2_cat): |
| 43492 | read_only | _dir_action_u = str(prediction.get("action", "") or "").upper() |
| 43495 | read_only | _dir_htf_bias = int(_batch_tf_agg.get("bias_dir", 0) or 0) |
| 43503 | read_only | _dir_conf = float(prediction.get("confidence", 0) or 0) |
| 43524 | read_only | _throttle_action_u = str(prediction.get("action", "") or "").upper() |
| 43530 | read_only | _throttle_last = self._last_signal_ts_per_symbol.get(symbols[i], 0) |
| 43543 | read_only | _final_act = str(prediction.get("action", "") or "").upper() |
| 43565 | read_only | conf = p.get("confidence") |
| 43675 | write_signal | # Publish a single summary per batch to wma:predictions_qc for monitoring. |
| 43679 | read_only | _pqc_stream_maxlen = int(getattr(self.main_config, 'PQC_STREAM_MAXLEN', 50000)) |
| 43680 | read_only | if _pqc_stream_enabled and self._signal_redis: |
| 43685 | read_only | _a = str(_p.get('action') or _p.get('predicted_action') or 'UNKNOWN').upper() |
| 43686 | read_only | _pqc_dir_dist[_a] = _pqc_dir_dist.get(_a, 0) + 1 |
| 43692 | read_only | _aname = str(_AID_PQC.get(int(_idx), 'UNKNOWN')).upper() |
| 43693 | read_only | _pqc_raw_dir_dist[_aname] = _pqc_raw_dir_dist.get(_aname, 0) + 1 |
| 43710 | read_only | _pqc_long_frac = (_pqc_dir_dist.get('OPEN_LONG', 0) + _pqc_dir_dist.get('CLOSE_SHORT_OPEN_LONG', 0)) / max(_pqc_total, 1) |
| 43729 | write_signal | self._signal_redis.xadd(_pqc_stream_name, _pqc_payload, maxlen=_pqc_stream_maxlen) |
| 43735 | write_metric | logger.debug("PQC_STREAM publish error: %s", _pqc_err) |
| 43740 | read_only | # set a Redis latch blocking downstream execution for cooldown period. |
| 43743 | read_only | if _pqc_stuck_enabled and self._signal_redis: |
| 43747 | read_only | self._pqc_direction_window = _deque_pqc(maxlen=_win_size) |
| 43753 | read_only | (_stuck_dir.get('OPEN_LONG', 0) + _stuck_dir.get('CLOSE_SHORT_OPEN_LONG', 0)) |
| 43765 | read_only | if len(_win) >= _win.maxlen: |
| 43770 | read_only | # Trainer appears stuck — set Redis latch |
| 43774 | write_signal | self._signal_redis.set(_pqc_latch_key, str(_pqc_until_ms), ex=_pqc_cooldown) |
| 43782 | read_only | elif len(_win) >= _win.maxlen and int(time.time()) % 300 < 35: |
| 43807 | write_metric | from utils.decision_bus import publish_decision_record |
| 43810 | read_only | symbol = payload.get("symbol", "UNKNOWN") |
| 43811 | read_only | timeframe = payload.get("timeframe", "") or "multi" |
| 43823 | read_only | action_field = payload.get("action") |
| 43824 | read_only | action_name = payload.get("action_name") or payload.get("predicted_action") or str(action_field) |
| 43829 | read_only | action_name = _AID2NAME_LOG.get(action_idx, action_name) |
| 43833 | read_only | confidence_adj = float(payload.get("confidence", payload.get("model_confidence", 0.0)) or 0.0) |
| 43834 | read_only | confidence_raw = float(payload.get("ppo_confidence", confidence_adj) or 0.0) |
| 43838 | read_only | pos_side = pos.get("side", "NONE") |
| 43839 | read_only | pos_qty = float(pos.get("size", 0.0) or 0.0) |
| 43840 | read_only | pos_pnl_pct = float(pos.get("pnl_pct", 0.0) or 0.0) |
| 43841 | read_only | pos_age = int(pos.get("age_seconds", 0) or 0) |
| 43842 | read_only | stop_loss_price = pos.get("stop_loss_price") or None |
| 43853 | read_only | liq_data = self.redis.hgetall(liq_key) if getattr(self, "redis", None) else {} |
| 43854 | read_only | liq_ll = float(liq_data.get("liquidation_long_level", 0.0) or 0.0) |
| 43855 | read_only | liq_sl = float(liq_data.get("liquidation_short_level", 0.0) or 0.0) |
| 43856 | read_only | liq_ls = float(liq_data.get("liquidation_long_strength", 0.0) or 0.0) |
| 43857 | read_only | liq_ss = float(liq_data.get("liquidation_short_strength", 0.0) or 0.0) |
| 43858 | read_only | liq_last_event_ts = int(liq_data.get("liquidation_last_event_ts", 0) or 0) |
| 43864 | read_only | constraints = payload.get("constraints_applied") or [] |
| 43867 | read_only | blocked_liquidity = any("LIQUIDITY" in str(r).upper() for r in constraints) or payload.get("margin_blocked", False) |
| 43869 | read_only | cooldown_active = bool(payload.get("cooldown_active", False)) |
| 43870 | read_only | min_hold_active = bool(payload.get("min_hold_active", False)) |
| 43873 | read_only | if payload.get("margin_blocked") and "R_LIQUIDITY_BLOCK" not in reason_codes: |
| 43884 | read_only | "decision_id": payload.get("decision_id") or payload.get("signal_id") or f"{ts_ms}-{symbol}-{timeframe}", |
| 43885 | read_only | "account": payload.get("account_id") or payload.get("account") or "primary", |
| 43889 | read_only | "skip_reason": payload.get("skip_reason") or payload.get("reason"), |
| 43894 | read_only | "predicted_action": payload.get("predicted_action", action_name), |
| 43908 | read_only | "trailing_stop_active": payload.get("trailing_stop_active", False), |
| 43916 | read_only | "scenario_adjusted_logit": payload.get("scenario_adjusted_logit"), |
| 43917 | read_only | "scenario_logit_delta": payload.get("scenario_logit_delta"), |
| 43918 | read_only | "scenario_top_action": payload.get("scenario_top_action"), |
| 43919 | read_only | "scenario_ev": payload.get("scenario_ev"), |
| 43920 | read_only | "scenario_liq_prob": payload.get("scenario_liq_prob"), |
| 43921 | read_only | "move_intensity": payload.get("move_intensity"), |
| 43922 | read_only | "move_direction": payload.get("move_direction"), |
| 43923 | read_only | "move_type": payload.get("move_type"), |
| 43924 | read_only | "move_top_contributors": payload.get("move_top_contributors") or payload.get("top_contributors") or [], |
| 43925 | read_only | "tf_votes": payload.get("tf_votes") or {}, |
| 43926 | read_only | "tf_bias_dir": payload.get("tf_bias_dir"), |
| 43927 | read_only | "tf_timing_dir": payload.get("tf_timing_dir"), |
| 43928 | read_only | "tf_conflict_score": payload.get("tf_conflict_score"), |
| 43929 | read_only | "mtf_scenario_id": payload.get("mtf_scenario_id"), |
| 43930 | read_only | "primary_tf": payload.get("primary_tf"), |
| 43931 | read_only | "contrary_htf_bias": payload.get("contrary_htf_bias"), |
| 43933 | read_only | "bias_dir": payload.get("tf_bias_dir"), |
| 43934 | read_only | "timing_dir": payload.get("tf_timing_dir"), |
| 43935 | read_only | "conflict_score": payload.get("tf_conflict_score"), |
| 43936 | read_only | "tlc_final_action": payload.get("tlc_final_action") or payload.get("final_action") or action_name, |
| 43937 | read_only | "tlc_size_multiplier": payload.get("tlc_size_multiplier"), |
| 43938 | read_only | "tlc_reason_codes": payload.get("tlc_reason_codes") or [], |
| 43945 | read_only | decision_maxlen = int(getattr(self.main_config, "DECISION_STREAM_MAXLEN", 50000) or 50000) |
| 43947 | read_only | decision_maxlen = 50000 |
| 43949 | read_only | _rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 43950 | write_metric | _decision_stream_id = publish_decision_record(_rc, record, maxlen=decision_maxlen) |
| 43957 | read_only | record.get("decision_id"), |
| 43960 | write_metric | logger.warning(f"[DECISION_BUS_FAIL] exception while publishing decision record: {bus_err}") |
| 43968 | write_signal | It does NOT publish trading signals and does NOT alter strategy outputs. |
| 43987 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 44003 | read_only | last_seen_ms = int(recent.get(pair_key, 0) or 0) |
| 44016 | read_only | uf_data = rc.hgetall(f"unified_features:{symbol}:{tf}") or {} |
| 44025 | read_only | if uf_data.get("ts_ms") is not None: |
| 44026 | read_only | uf_ts_ms = int(float(uf_data.get("ts_ms") or 0)) |
| 44027 | read_only | elif uf_data.get("timestamp_ms") is not None: |
| 44028 | read_only | uf_ts_ms = int(float(uf_data.get("timestamp_ms") or 0)) |
| 44029 | read_only | elif uf_data.get("timestamp") is not None: |
| 44030 | read_only | uf_ts_ms = int(float(uf_data.get("timestamp") or 0) * 1000) |
| 44038 | read_only | pred = rc.hgetall(f"prediction:{symbol}:{tf}") or {} |
| 44045 | read_only | p_ts = float(pred.get("timestamp") or 0.0) |
| 44071 | write_metric | from utils.decision_bus import publish_decision_record |
| 44072 | read_only | decision_maxlen = int(getattr(self.main_config, "DECISION_STREAM_MAXLEN", 50000) or 50000) |
| 44073 | write_checkpoint_metadata | sid = publish_decision_record(rc, payload, maxlen=decision_maxlen) |
| 44077 | write_metric | logger.warning(f"[DECISION_COVERAGE_SWEEP] failed_publish symbol={symbol} tf={tf} reason={reason}") |
| 44087 | write_checkpoint_metadata | def _publish_decision(self, payload: dict): |
| 44089 | write_checkpoint_metadata | Publish a single decision payload to Redis stream. |
| 44095 | write_signal | if not getattr(config, "PUBLISH_SIGNALS", True): |
| 44099 | read_only | symbol = payload.get("symbol", "UNKNOWN") |
| 44100 | read_only | timeframe = payload.get("timeframe") or payload.get("tf") or "" |
| 44103 | read_only | conf = float(payload.get("confidence", payload.get("model_confidence", 0.0))) |
| 44105 | write_metric | # Default publish flag for decision logs |
| 44106 | write_checkpoint_metadata | payload["published"] = False |
| 44108 | write_signal | # PRODUCTION GUARD: Never publish NaN/Inf confidence values |
| 44111 | write_signal | logger.warning(f"[PUBLISH] Dropping signal with NaN confidence ({payload.get('symbol')} {payload.get('timeframe')})") |
| 44114 | read_only | payload["constraints_applied"] = list(payload.get("constraints_applied", []) or []) + ["INVALID_CONF_NAN"] |
| 44120 | write_signal | logger.warning(f"[PUBLISH] Dropping signal with Inf confidence ({payload.get('symbol')} {payload.get('timeframe')})") |
| 44123 | read_only | payload["constraints_applied"] = list(payload.get("constraints_applied", []) or []) + ["INVALID_CONF_INF"] |
| 44135 | read_only | _action_raw = payload.get("action") or payload.get("action_name") |
| 44145 | read_only | _cat_u = str(payload.get("action_category") or "").upper() |
| 44148 | read_only | _is_hedge_action = bool(payload.get("hedge_intent")) or (_cat_u == "HEDGE") or ("HEDGE" in _action_u) |
| 44169 | write_metric | # TOP PROBABILITY GATE (Feb 2026 Audit Fix #1 — publish-time defense) |
| 44176 | read_only | _tp_prob = float(payload.get("top_action_prob", 0.0) or 0.0) |
| 44197 | read_only | _ag_redis = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 44198 | read_only | if _ag_redis: |
| 44199 | read_only | _ag = AdaptiveGate(_ag_redis) |
| 44201 | read_only | _ag_notional = float(payload.get("notional_usd", 0) or 0) |
| 44225 | read_only | _old_margin = float(payload.get("margin_usd", 0) or 0) |
| 44226 | read_only | _old_notional = float(payload.get("notional_usd", 0) or 0) |
| 44227 | read_only | _old_pct = float(payload.get("position_size_pct", 0) or 0) |
| 44238 | read_only | float(payload.get("margin_usd", 0)), |
| 44244 | write_metric | logger.debug("[ADAPTIVE_GATE] publish-time check skipped: %s", _ag_err) |
| 44251 | read_only | ppo_conf = payload.get("ppo_confidence", conf) |
| 44252 | read_only | masa_conf = payload.get("masa_confidence", 0.0) |
| 44263 | read_only | _sym = payload.get("symbol", "UNKNOWN") |
| 44264 | read_only | _act = payload.get("action") or payload.get("action_name") or "UNKNOWN" |
| 44274 | read_only | htf_bias = payload.get("htf_bias", 0) |
| 44275 | read_only | vhtf_bias = payload.get("vhtf_bias", 0) |
| 44276 | read_only | action_name_upper = str(payload.get("action") or payload.get("action_name") or "").upper() |
| 44312 | read_only | pos_pnl_pct = float(pos.get("pnl_pct", 0) or pos.get("pnl_percentage", 0) or 0) |
| 44313 | read_only | pos_side = pos.get("side", "").upper() |
| 44336 | read_only | self._last_recommended_lev = payload.get("recommended_leverage") |
| 44337 | read_only | self._last_recommended_pos_pct = payload.get("recommended_position_pct") |
| 44342 | read_only | ppo_conf = payload.get("ppo_confidence", conf) |
| 44343 | read_only | masa_conf = payload.get("masa_confidence", 0.0) |
| 44344 | read_only | lev = payload.get("recommended_leverage", "N/A") |
| 44345 | read_only | pos_pct = payload.get("recommended_position_pct", 0.0) * 100.0 if payload.get("recommended_position_pct") else 0.0 |
| 44346 | read_only | action_name = payload.get("action", "UNKNOWN") |
| 44347 | read_only | symbol = payload.get("symbol", "UNKNOWN") |
| 44348 | read_only | timeframe = payload.get("timeframe", "UNKNOWN") |
| 44351 | write_risk_state | # NO-LOSS GUARD (publish-time): never emit STOP-LOSS-driven CLOSE_*. |
| 44356 | read_only | _dec = str(payload.get("decision_reason") or payload.get("reason") or "") |
| 44358 | read_only | _acct = str(payload.get("account_id") or self._resolve_target_account() or "") |
| 44364 | read_only | _is_recovery = bool(payload.get("trainer_recovery_mode")) or bool(payload.get("recovery_rebalance")) or (str(payload.get("action_category") or "").upper() == "RECOVERY") or ("recovery" in str(payload.get("source") or "").lower()) |
| 44387 | write_metric | # EQUITY FAIL-CLOSED: drop publish if equity is unavailable or non-positive |
| 44390 | read_only | equity = float(portfolio_state.get("total_balance", 0.0) or 0.0) |
| 44392 | write_signal | logger.warning(f"🚫 [PUBLISH] Dropping signal {symbol} {timeframe} due to invalid equity={equity:.2f}") |
| 44397 | write_metric | logger.warning(f"⚠️ [PUBLISH] Equity check failed ({symbol} {timeframe}): {eq_err}") |
| 44401 | read_only | if payload.get("recommended_position_pct") is None and payload.get("position_size_pct") is not None: |
| 44402 | read_only | payload["recommended_position_pct"] = payload.get("position_size_pct") |
| 44403 | read_only | if payload.get("margin_usd", 0.0) <= 0 and equity > 0 and payload.get("recommended_position_pct") is not None: |
| 44405 | read_only | pct = float(payload.get("recommended_position_pct", 0.0)) / 100.0 |
| 44406 | read_only | lev_for_flip = float(payload.get("recommended_leverage") or payload.get("leverage") or 1.0) |
| 44418 | read_only | # HybridTrainer uses self.redis, GPUForcedPPO uses self._signal_redis |
| 44419 | read_only | hb_redis = getattr(self, 'redis', None) or getattr(self, '_signal_redis', None) |
| 44421 | read_only | hedge_build_active = hb_redis.exists(hedge_key) if hb_redis else False |
| 44424 | read_only | action_category = payload.get('action_category', 'OPEN_RISK') |
| 44425 | read_only | action_name = payload.get('action', '') |
| 44460 | read_only | current_pos_pct = payload.get("recommended_position_pct", 0.0) |
| 44474 | write_metric | # MARGIN VALIDATION: Check BEFORE publishing to any channel |
| 44499 | read_only | leverage = payload.get("recommended_leverage", 10) |
| 44500 | read_only | position_size_pct = payload.get("recommended_position_pct", 5.0) |
| 44503 | read_only | acct = payload.get("account_id") or payload.get("target_account_id") or payload.get("account") |
| 44509 | read_only | hedge_intent = bool(payload.get("hedge_intent")) or (str(payload.get("action_category") or "").upper() == "HEDGE") or action_u.startswith(("OPEN_HEDGE_", "ADD_HEDGE_")) |
| 44540 | write_metric | # DON'T publish to trader stream when margin is exhausted |
| 44546 | read_only | sid = str(payload.get("signal_id") or payload.get("ts_ms") or |
| 44547 | read_only | f"{payload.get('symbol')}:{payload.get('timeframe')}:{int(time.time())}") |
| 44549 | read_only | last = self._tg_last_sent.get(sid, 0) |
| 44555 | read_only | payload.get("timeframe", ""), |
| 44582 | read_only | f"After-trade util: {margin_check.get('projected_utilization', 0):.1f}%" |
| 44585 | write_metric | # Emit audit log before publishing (covers both margin-validated and non-margin paths) |
| 44589 | write_metric | # and downstream deconfliction/publish (backward-compatible). |
| 44599 | read_only | symbol_for_target = str(payload.get("symbol") or "") |
| 44600 | read_only | tf_for_target = str(payload.get("timeframe") or "") |
| 44601 | read_only | if symbol_for_target and tf_for_target and payload.get("price_target") is None: |
| 44631 | read_only | # Best effort current price from Redis (non-blocking). |
| 44634 | read_only | px = self._signal_redis.get(f"price:{symbol_for_target}") if hasattr(self, "_signal_redis") else None |
| 44665 | read_only | atr_pct = float(payload.get("atr_pct") or 0.0) |
| 44668 | read_only | _rc_c = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 44673 | read_only | _pt = _compute_price_target( |
| 44682 | write_signal | # 0.5) Cache raw prediction for multi-TF even if publish ultimately fails |
| 44683 | read_only | symbol = payload.get("symbol", "UNKNOWN") |
| 44684 | read_only | timeframe = payload.get("timeframe", "") |
| 44694 | write_metric | "published": 0, |
| 44698 | read_only | if payload.get("price_target") is not None: |
| 44699 | read_only | pred_map["price_target"] = str(payload.get("price_target")) |
| 44700 | read_only | if payload.get("price_target_pct") is not None: |
| 44701 | read_only | pred_map["price_target_pct"] = str(payload.get("price_target_pct")) |
| 44702 | read_only | if payload.get("price_target_direction") is not None: |
| 44703 | read_only | pred_map["price_target_direction"] = str(payload.get("price_target_direction")) |
| 44707 | write_signal | self._signal_redis.hset(pred_key, mapping=pred_map) |
| 44708 | read_only | self._signal_redis.expire(pred_key, 1800)  # 30 min TTL (was 120s - caused deadlock) |
| 44710 | write_signal | logger.debug(f"Failed to cache pre-publish prediction {pred_key}: {cache_err}") |
| 44714 | write_signal | # that normally calls _build_trade_signal in _publish_buffered_signals |
| 44720 | write_signal | logger.debug(f"[_publish_decision] ppo_model not available for _build_trade_signal, using raw payload") |
| 44722 | write_metric | # CRITICAL (Jan 2026): When ORCHESTRATOR_WORKER_MODE=publish, use _emit_proposal() |
| 44723 | write_signal | # instead of _publish_signal_payload() to route through orchestrator worker. |
| 44729 | write_metric | str(ORCHESTRATOR_WORKER_MODE).lower() == "publish" |
| 44737 | read_only | act_name = str(payload.get("action_name") or payload.get("action") or "").upper() |
| 44747 | write_checkpoint_metadata | logger.info(f"📤 [PUBLISH_DECISION_PROPOSAL] {payload.get('account_id')}:{symbol} {act_name} emitted to orchestrator") |
| 44749 | write_checkpoint_metadata | logger.warning(f"❌ [PUBLISH_DECISION_PROPOSAL] {payload.get('account_id')}:{symbol} {act_name} failed to emit") |
| 44752 | write_metric | # Legacy path: direct publish (only when orchestrator disabled/shadow) |
| 44753 | write_signal | built_payload = self._publish_signal_payload(payload, contract_required=True) |
| 44757 | write_risk_state | # WHY_NO_OPEN_RISK: mark that this symbol did get an OPEN_RISK publish this cycle |
| 44760 | read_only | act0 = str(built_payload.get("action_name") or built_payload.get("action") or "") |
| 44763 | write_risk_state | self._why_no_open_risk_mark_published(str(symbol)) |
| 44767 | write_checkpoint_metadata | built_payload["published"] = True |
| 44768 | write_checkpoint_metadata | self._log_decision_record(built_payload, stage="published") |
| 44770 | write_signal | # 1.5) Cache prediction in Redis hash for multi-TF lookups (mark published) |
| 44780 | write_metric | "published": 1, |
| 44784 | read_only | if built_payload.get("price_target") is not None: |
| 44785 | read_only | pred_map["price_target"] = str(built_payload.get("price_target")) |
| 44786 | read_only | if built_payload.get("price_target_pct") is not None: |
| 44787 | read_only | pred_map["price_target_pct"] = str(built_payload.get("price_target_pct")) |
| 44788 | read_only | if built_payload.get("price_target_direction") is not None: |
| 44789 | read_only | pred_map["price_target_direction"] = str(built_payload.get("price_target_direction")) |
| 44793 | write_signal | self._signal_redis.hset(pred_key, mapping=pred_map) |
| 44794 | read_only | self._signal_redis.expire(pred_key, 1800)  # 30 min TTL (was 120s - caused deadlock) |
| 44798 | write_risk_state | # 1.6) Record cooldown only after successful publish (robust: getattr to avoid AttributeError) |
| 44810 | read_only | sid = f"{built_payload.get('symbol')}:{built_payload.get('timeframe')}" |
| 44812 | read_only | if (now_s - self._tg_last_sent.get(sid, 0)) > self._tg_cooldown_s: |
| 44813 | read_only | action_name = built_payload.get("action_name") or str(built_payload.get("action", "UNKNOWN")).upper() |
| 44814 | read_only | regime_info = built_payload.get("market_regime_info") or None |
| 44817 | read_only | built_payload.get("timeframe", ""), |
| 44829 | write_metric | logger.exception(f"Failed to publish single decision: {e}") |
| 44831 | write_signal | def _publish_batch_predictions(self, preds, *, source="GPU_BATCH", debug=False): |
| 44833 | write_signal | Publish already-prepared prediction dicts using _publish_decision(). |
| 44842 | read_only | conf = p.get("confidence", p.get("model_confidence", None)) |
| 44849 | write_metric | logger.info(f"[{source}] No publishable items after final sanitization (all dropped).") |
| 44854 | write_metric | # ── TRAINER INTENT PUBLISHER (GPU Batch Path) ────────────────────── |
| 44855 | write_signal | # Publish intent for every symbol in the batch before executing signals. |
| 44857 | write_signal | from risk.trainer_intent import publish_intent, infer_direction_from_action |
| 44858 | read_only | _intent_redis = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 44859 | read_only | if _intent_redis is not None: |
| 44862 | read_only | _bp_action = str(_bp.get("action") or _bp.get("action_name") or "") |
| 44863 | read_only | _bp_symbol = str(_bp.get("symbol") or "") |
| 44864 | read_only | _bp_conf = float(_bp.get("confidence") or _bp.get("model_confidence") or 0.0) |
| 44865 | read_only | _bp_tf = str(_bp.get("timeframe") or "") |
| 44867 | write_metric | publish_intent( |
| 44868 | read_only | redis_client=_intent_redis, |
| 44879 | write_metric | logger.debug(f"[TRAINER_INTENT] batch intent publish failed: {_bi_err}") |
| 44881 | write_metric | published = 0 |
| 44884 | write_metric | self._publish_decision(p)  # <- your single source of truth |
| 44885 | write_metric | published += 1 |
| 44887 | write_metric | logger.info(f"[{source}] Published #{i+1}: {p.get('symbol')} {p.get('timeframe')} " |
| 44888 | read_only | f"{p.get('action')} conf={p.get('confidence')}") |
| 44890 | write_metric | logger.error(f"[{source}] Failed to publish item #{i+1}: {e}") |
| 44893 | write_metric | if published > 0: |
| 44894 | write_signal | confidences = [p.get("confidence", p.get("model_confidence", 0.0)) for p in preds[:published]] |
| 44895 | write_signal | ppo_confs = [p.get("ppo_confidence", 0.0) for p in preds[:published]] |
| 44896 | write_signal | masa_confs = [p.get("masa_confidence", 0.0) for p in preds[:published]] |
| 44902 | write_signal | logger.info(f"[{source}] Published {published} signals / [SUMMARY] mean final={mean_final:.3f} (ppo={mean_ppo:.3f}, masa={mean_masa:.3f})") |
| 44904 | write_metric | return published |
| 44906 | write_signal | def _publish_decisions_batch(self, actions, confidences=None, prices=None, ts: float = None): |
| 44907 | write_metric | """Publish batch of decisions for all environments using Redis pipeline""" |
| 44911 | write_signal | if not getattr(config, "PUBLISH_SIGNALS", True): |
| 44918 | write_signal | signals_published = [] |
| 44938 | read_only | available_margin = portfolio_state.get('available_balance', 0.0) |
| 44958 | write_signal | built = self._publish_signal_payload(payload, contract_required=True) |
| 44960 | write_signal | signals_published.append(f"{sym}:{action_text}({c:.2f})") |
| 44968 | read_only | 'overall_regime': regime_analysis.get('overall', 'normal'), |
| 44969 | read_only | 'volatility': regime_analysis.get('volatility', 0.5), |
| 44970 | read_only | 'stress_level': regime_analysis.get('stress_level', 0.3), |
| 44971 | read_only | 'timeframe_regimes': regime_analysis.get('timeframe_regimes', {}), |
| 44977 | write_signal | if signals_published: |
| 44978 | write_signal | print(f"📡 [SIGNALS] Published {len(signals_published)} signals: {', '.join(signals_published)}", flush=True) |
| 44979 | write_signal | logger.info(f"📡 Published signals: {', '.join(signals_published)}") |
| 44981 | write_metric | logger.exception(f"Failed to publish batch decisions: {e}") |
| 44983 | write_signal | def _publish_decisions_batch_v2(self, actions, confidences=None, prices=None, ts: float = None): |
| 44984 | write_signal | """NEW: Publish batch with signal deconfliction (Production TA Section 1) |
| 44993 | write_signal | 7. Publish one net action per symbol |
| 45006 | write_signal | if not getattr(config, "PUBLISH_SIGNALS", True): |
| 45019 | write_signal | logger.debug("📭 No signals to publish (all HOLD)") |
| 45023 | write_metric | published_count = 0 |
| 45063 | write_metric | "source": getattr(config, "PUBLISH_SOURCE_TAG", "trainer"), |
| 45084 | write_signal | built = self._publish_signal_payload(payload, contract_required=True) |
| 45086 | write_metric | published_count += 1 |
| 45103 | read_only | 'overall_regime': regime_analysis.get('overall', 'normal'), |
| 45104 | read_only | 'volatility': regime_analysis.get('volatility', 0.5), |
| 45105 | read_only | 'stress_level': regime_analysis.get('stress_level', 0.3), |
| 45106 | read_only | 'timeframe_regimes': regime_analysis.get('timeframe_regimes', {}), |
| 45134 | write_signal | logger.info(f"✅ Deconflicted signals published: {published_count} symbols " |
| 45138 | write_metric | logger.exception(f"❌ Failed to publish deconflicted decisions: {e}") |
| 45141 | read_only | """Query Redis for current position state from traders across all accounts |
| 45167 | read_only | # Get Redis client |
| 45168 | read_only | redis_client = None |
| 45169 | read_only | if hasattr(self.config, 'redis_client') and self.config.redis_client: |
| 45170 | read_only | redis_client = self.config.redis_client |
| 45171 | read_only | elif hasattr(self, 'redis') and self.redis: |
| 45172 | read_only | redis_client = self.redis |
| 45174 | read_only | import redis as redis_module |
| 45175 | read_only | redis_client = redis_module.Redis(host='localhost', port=6379, decode_responses=True) |
| 45177 | read_only | if not redis_client: |
| 45193 | read_only | if redis_client.type(ck) != "hash": |
| 45195 | read_only | fields = redis_client.hgetall(ck) or {} |
| 45197 | read_only | raw = fields.get(f"{symbol}:{side}") |
| 45219 | read_only | side = str(payload.get('side', 'NONE')).upper() |
| 45220 | read_only | size = float(payload.get('size', 0.0) or 0.0) |
| 45226 | read_only | 'entry_price': float(payload.get('entry_price', 0)), |
| 45227 | read_only | 'current_price': float(payload.get('current_price', 0)), |
| 45228 | read_only | 'unrealized_pnl': float(payload.get('unrealized_pnl', 0)), |
| 45229 | read_only | 'pnl_pct': float(payload.get('pnl_pct', 0)), |
| 45230 | read_only | 'leverage': int(payload.get('leverage', 1)), |
| 45231 | read_only | 'margin_used': float(payload.get('margin_used', 0)), |
| 45232 | write_metric | # Prefer [REDACTED]-provided liquidation price as published by traders (cross/multi-asset aware) |
| 45233 | read_only | 'liquidation_price': float(payload.get('liquidation_price', 0) or 0), |
| 45234 | read_only | 'timestamp': float(payload.get('timestamp', time.time())) |
| 45247 | write_metric | skipped_wrongtype = set() |
| 45250 | read_only | key_type = redis_client.type(position_key) |
| 45263 | read_only | raw_hash = redis_client.hgetall(position_key) |
| 45289 | read_only | if not pos_data.get('side') and not pos_data.get('size'): |
| 45293 | read_only | logger.info(f"[POSITION_PARSED] {symbol} / key={position_key} / side={pos_data.get('side')} / size={pos_data.get('size')}") |
| 45295 | read_only | position_json = redis_client.get(position_key) |
| 45300 | read_only | side = str(pos_data.get('side', 'NONE')).upper() |
| 45301 | read_only | size = float(pos_data.get('size', 0) or 0) |
| 45308 | read_only | 'entry_price': float(pos_data.get('entry_price', 0)), |
| 45309 | read_only | 'current_price': float(pos_data.get('current_price', 0)), |
| 45310 | read_only | 'unrealized_pnl': float(pos_data.get('unrealized_pnl', 0)), |
| 45311 | read_only | 'pnl_pct': float(pos_data.get('pnl_pct', 0)), |
| 45312 | read_only | 'leverage': int(pos_data.get('leverage', 1)), |
| 45313 | read_only | 'margin_used': float(pos_data.get('margin_used', 0)), |
| 45314 | read_only | 'liquidation_price': float(pos_data.get('liquidation_price', 0) or 0), |
| 45315 | read_only | 'timestamp': float(pos_data.get('timestamp', time.time())) |
| 45324 | read_only | 'entry_price': float(pos_data.get('entry_price', 0)), |
| 45325 | read_only | 'current_price': float(pos_data.get('current_price', 0)), |
| 45326 | read_only | 'unrealized_pnl': float(pos_data.get('unrealized_pnl', 0)), |
| 45327 | read_only | 'pnl_pct': float(pos_data.get('pnl_pct', 0)), |
| 45328 | read_only | 'leverage': int(pos_data.get('leverage', 1)), |
| 45329 | read_only | 'margin_used': float(pos_data.get('margin_used', 0)), |
| 45330 | read_only | 'liquidation_price': float(pos_data.get('liquidation_price', 0) or 0), |
| 45331 | read_only | 'timestamp': float(pos_data.get('timestamp', time.time())) |
| 45340 | write_metric | # re-deriving it here and instead use [REDACTED]-provided liquidationPrice published by traders. |
| 45347 | read_only | lp = float(p.get("liquidation_price", 0) or 0) |
| 45348 | read_only | cp = float(p.get("current_price", 0) or 0) |
| 45554 | read_only | is_extreme = regime.get('is_extreme_volatility', False) |
| 45555 | read_only | overall_regime = regime.get('overall', 'normal') |
| 45595 | read_only | if not pos.get("has_position"): |
| 45598 | read_only | current_leverage = pos.get("leverage", 1) |
| 45602 | read_only | regime = mp.get("regime_analysis", {}) |
| 45603 | read_only | vol = mp.get("volatility_5m", 0.5) |
| 45604 | read_only | stress = mp.get("stress_level", 0.3) |
| 45620 | read_only | "reasoning": f"Market stress: {stress:.2f}, volatility: {vol:.2f}, regime: {regime.get('overall', 'unknown')}", |
| 45623 | read_only | "market_regime": regime.get('overall', 'normal'), |
| 45633 | write_signal | built = self._publish_signal_payload(payload, contract_required=False) |
| 45635 | write_signal | logger.info(f"✅ [LEV-CAP] Published ADJUST_LEVERAGE signal: {symbol} {current_leverage}x→{cap}x") |
| 45637 | write_signal | logger.error(f"[LEV-CAP] Failed to publish adjustment signal: {e}") |
| 45668 | read_only | reason_code = str(feedback.get('reason_code') or '').upper() |
| 45669 | read_only | account_id = str(feedback.get('account_id') or 'primary') |
| 45670 | read_only | symbol = feedback.get('symbol') |
| 45671 | read_only | action = feedback.get('action') |
| 45688 | write_signal | Consumes from 'executed_signals' stream published by trader |
| 45705 | write_metric | hedge_build_symbols = set()  # Track symbols in HEDGE_BUILD state |
| 45712 | read_only | result = self._signal_redis.xread( |
| 45752 | read_only | event_type = str(feedback.get('event_type') or '').upper() |
| 45755 | read_only | feedback.get('reason_code') and feedback.get('status') and feedback.get('category') |
| 45757 | read_only | reason_code = str(feedback.get('reason_code') or '').upper() |
| 45758 | read_only | account_id = str(feedback.get('account_id') or 'primary') |
| 45759 | read_only | symbol = feedback.get('symbol') |
| 45760 | read_only | action = feedback.get('action') |
| 45771 | read_only | ts_ms=int(feedback.get('ts_ms') or (time.time() * 1000)), |
| 45774 | read_only | signal_id=str(feedback.get('signal_id') or ''), |
| 45776 | read_only | category=str(feedback.get('category') or 'SYSTEM'), |
| 45777 | read_only | status=str(feedback.get('status') or 'UNKNOWN'), |
| 45778 | read_only | reason_code=str(feedback.get('reason_code') or ''), |
| 45779 | read_only | portfolio=feedback.get('portfolio', {}) or {}, |
| 45780 | read_only | exec=feedback.get('exec', {}) or {}, |
| 45796 | read_only | symbol = feedback.get('symbol') |
| 45797 | read_only | side = feedback.get('side') |
| 45798 | read_only | exit_reason = feedback.get('exit_reason', feedback.get('reason', 'unknown')) |
| 45806 | read_only | self._signal_redis.setex( |
| 45831 | read_only | account_id = str(feedback.get('account_id') or 'primary') |
| 45856 | read_only | self._signal_redis.setex(risk_key, ttl, json.dumps(value)) |
| 45867 | read_only | symbol=feedback.get('symbol', 'UNKNOWN'), |
| 45868 | read_only | signal_id=feedback.get('signal_id', ''), |
| 45869 | read_only | action=feedback.get('action', event_type), |
| 45874 | read_only | 'equity_usd': feedback.get('equity_usd', 0), |
| 45875 | read_only | 'pnl_pct': feedback.get('pnl_pct', 0), |
| 45892 | read_only | f"block={block_categories} equity_usd={feedback.get('equity_usd')}" |
| 45897 | read_only | f"block={block_categories} pnl_pct={feedback.get('pnl_pct')}" |
| 45907 | read_only | if not self._signal_redis.exists(hedge_key): |
| 45946 | read_only | # Trigger predictions immediately when new features arrive via Redis pub/sub |
| 45969 | read_only | """Synchronous event-driven listener using Redis pub/sub (runs in thread)""" |
| 45971 | read_only | from utils.redis_client import get_redis |
| 45978 | read_only | # Create dedicated Redis connection for pub/sub |
| 45979 | read_only | redis_client = get_redis() |
| 45980 | read_only | pubsub = redis_client.pubsub() |
| 45981 | read_only | pubsub.subscribe(FEATURE_UPDATE_CHANNEL) |
| 45983 | read_only | logger.info(f"[EVENT-PREDICT] Subscribed to channel: {FEATURE_UPDATE_CHANNEL}") |
| 46017 | read_only | last_trigger = self._event_debounce_pending.get(key, 0) |
| 46048 | read_only | # Get features from Redis |
| 46050 | read_only | features = self._signal_redis.hgetall(feature_key) if self._signal_redis else None |
| 46063 | read_only | ts_ms = int(decoded_features.get('ts_ms', 0)) |
| 46076 | write_metric | # C1/C2: Immediate publish mode - no buffering |
| 46085 | write_metric | suppress_publish=suppress |
| 46100 | read_only | """Resolve preferred account_id from env or Redis active_account.""" |
| 46106 | write_metric | # Only honor explicit operator intent. In multi-account live mode we publish to |
| 46277 | read_only | rc = self._signal_redis if self._signal_redis is not None else get_redis() |
| 46281 | write_metric | # PRIORITY 0: Trader-published equity snapshots (most accurate + always per-account) |
| 46282 | write_metric | # Traders publish `portfolio:equity:{account_id}` JSON frequently. Use this first to avoid |
| 46283 | read_only | # false "equity missing" fallbacks when the tracker is warming up or Redis hashes are absent. |
| 46290 | read_only | raw = rc.get(f"portfolio:equity:{aid}") |
| 46307 | read_only | ts = float(eq.get("timestamp", 0.0) or 0.0) |
| 46311 | read_only | eq_usd = float(eq.get("equity_usd", 0.0) or 0.0) |
| 46313 | read_only | avail_usd = float(eq.get("available_margin_usd", 0.0) or 0.0) |
| 46314 | read_only | used_usd = float(eq.get("used_margin_usd", 0.0) or 0.0) |
| 46315 | read_only | unreal_usd = float(eq.get("unrealized_pnl_usd", 0.0) or 0.0) |
| 46319 | read_only | wallet_usd = float(eq.get("wallet_balance_usd", 0.0) or 0.0) |
| 46345 | read_only | # Avoid relying on `scan_iter` because some Redis wrappers don't expose it. |
| 46346 | write_metric | eq_accounts: set[str] = set() |
| 46356 | write_metric | allowed_accounts = set(a.strip().lower() for a in (ACTIVE_TRADING_ACCOUNTS or []) if a) |
| 46358 | write_metric | allowed_accounts = set() |
| 46383 | read_only | ts = float(eq.get("timestamp", 0.0) or 0.0) |
| 46388 | read_only | eq_usd = float(eq.get("equity_usd", 0.0) or 0.0) |
| 46391 | read_only | avail_usd = float(eq.get("available_margin_usd", 0.0) or 0.0) |
| 46392 | read_only | used_usd = float(eq.get("used_margin_usd", 0.0) or 0.0) |
| 46393 | read_only | unreal_usd = float(eq.get("unrealized_pnl_usd", 0.0) or 0.0) |
| 46395 | read_only | wallet_usd = float(eq.get("wallet_balance_usd", 0.0) or 0.0) |
| 46438 | read_only | if tracker_state and tracker_state.get("total_equity") is not None: |
| 46439 | read_only | accounts = tracker_state.get("accounts", {}) or {} |
| 46442 | write_metric | allowed_accounts = set(a.strip().lower() for a in (ACTIVE_TRADING_ACCOUNTS or []) if a) |
| 46444 | write_metric | allowed_accounts = set() |
| 46447 | read_only | timestamp = float(tracker_state.get("timestamp", time.time())) |
| 46452 | read_only | pdata = accounts.get(account_id, {}) or {} |
| 46455 | read_only | "total_balance": float(pdata.get("equity", 0.0) or 0.0), |
| 46456 | read_only | "available_balance": float(pdata.get("available_balance", 0.0) or 0.0), |
| 46457 | read_only | "total_margin_used": float(pdata.get("used_margin", 0.0) or 0.0), |
| 46458 | read_only | "unrealized_pnl": float(pdata.get("unrealized_pnl", 0.0) or 0.0), |
| 46459 | read_only | "margin_utilization_pct": float(pdata.get("margin_ratio", 0.0) or 0.0), |
| 46460 | read_only | "position_count": int(pdata.get("position_count", 0) or 0), |
| 46461 | read_only | "positions": pdata.get("positions", []), |
| 46462 | read_only | "timestamp": float(pdata.get("timestamp", timestamp)), |
| 46466 | read_only | 'total_balance': float(pdata.get("equity", 0.0) or 0.0), |
| 46467 | read_only | 'available_balance': float(pdata.get("available_balance", 0.0) or 0.0), |
| 46468 | read_only | 'total_margin_used': float(pdata.get("used_margin", 0.0) or 0.0), |
| 46469 | read_only | 'margin_utilization_pct': float(pdata.get("margin_ratio", 0.0) or 0.0), |
| 46470 | read_only | 'unrealized_pnl': float(pdata.get("unrealized_pnl", 0.0) or 0.0), |
| 46471 | read_only | 'position_count': int(pdata.get("position_count", 0) or 0), |
| 46481 | read_only | total_equity = sum(float(v.get("equity", 0.0) or 0.0) for v in accounts.values()) |
| 46482 | read_only | total_available = sum(float(v.get("available_balance", 0.0) or 0.0) for v in accounts.values()) |
| 46483 | read_only | total_used = sum(float(v.get("used_margin", 0.0) or 0.0) for v in accounts.values()) |
| 46484 | read_only | total_unreal = sum(float(v.get("unrealized_pnl", 0.0) or 0.0) for v in accounts.values()) |
| 46497 | read_only | "total_balance": float(pdata.get("equity", 0.0) or 0.0), |
| 46498 | read_only | "available_balance": float(pdata.get("available_balance", 0.0) or 0.0), |
| 46499 | read_only | "total_margin_used": float(pdata.get("used_margin", 0.0) or 0.0), |
| 46500 | read_only | "unrealized_pnl": float(pdata.get("unrealized_pnl", 0.0) or 0.0), |
| 46501 | read_only | "margin_utilization_pct": float(pdata.get("margin_ratio", 0.0) or 0.0), |
| 46502 | read_only | "position_count": int(pdata.get("position_count", 0) or 0), |
| 46503 | read_only | "positions": pdata.get("positions", []), |
| 46504 | read_only | "timestamp": float(pdata.get("timestamp", timestamp)), |
| 46530 | read_only | 'position_count': sum(p.get('position_count', 0) for p in accounts.values()) if accounts else tracker_state.get('position_count', 0) or 0, |
| 46538 | write_metric | # Publish combined state to Redis for telemetry (NOT for per-account trading). |
| 46539 | write_metric | # IMPORTANT: Do NOT publish under `portfolio:state:*` because scanners treat that |
| 46543 | write_metric | rc.hset( |
| 46576 | read_only | available_balance = self._margin_metrics.get('available_balance', self._real_balance) |
| 46577 | read_only | margin_utilization_pct = self._margin_metrics.get('margin_utilization', 0.0) |
| 46586 | read_only | 'per_symbol_margin': {symbol: pos.get('position_margin', 0) for symbol, pos in self._real_positions.items()}, |
| 46592 | read_only | # PRIORITY 2: Multi-account Redis data from traders |
| 46601 | write_metric | # First, prefer the per-account equity snapshots published by traders: |
| 46609 | read_only | raw = rc.get(f"portfolio:equity:{aid}") |
| 46622 | write_metric | eq_accounts = set(accounts) |
| 46625 | write_metric | allowed_accounts = set(a.strip().lower() for a in (ACTIVE_TRADING_ACCOUNTS or []) if a) |
| 46627 | write_metric | allowed_accounts = set() |
| 46652 | read_only | ts = float(eq.get("timestamp", 0.0) or 0.0) |
| 46658 | read_only | eq_usd = float(eq.get("equity_usd", 0.0) or 0.0) |
| 46661 | read_only | avail_usd = float(eq.get("available_margin_usd", 0.0) or 0.0) |
| 46662 | read_only | used_usd = float(eq.get("used_margin_usd", 0.0) or 0.0) |
| 46663 | read_only | unreal_usd = float(eq.get("unrealized_pnl_usd", 0.0) or 0.0) |
| 46683 | write_metric | rc.hset( |
| 46702 | read_only | if a.get("account_id") == account_id: |
| 46704 | read_only | "total_balance": float(a.get("total_balance", 0.0) or 0.0), |
| 46705 | read_only | "available_balance": float(a.get("available_balance", 0.0) or 0.0), |
| 46706 | read_only | "total_margin_used": float(a.get("total_margin_used", 0.0) or 0.0), |
| 46707 | read_only | "margin_utilization_pct": float(a.get("margin_utilization_pct", 0.0) or 0.0), |
| 46708 | read_only | "unrealized_pnl": float(a.get("unrealized_pnl", 0.0) or 0.0), |
| 46732 | read_only | active = rc.get("portfolio:state:active_account") |
| 46767 | write_metric | seen = set() |
| 46771 | write_metric | allowed_accounts = set(a.strip().lower() for a in (ACTIVE_TRADING_ACCOUNTS or []) if a) |
| 46773 | write_metric | allowed_accounts = set() |
| 46781 | read_only | data = rc.hgetall(key) |
| 46785 | read_only | # Decode Redis bytes to strings for safe float parsing |
| 46794 | read_only | ts_raw = data.get("timestamp") or data.get("ts_ms") or 0 |
| 46804 | write_metric | rc.delete(key) |
| 46826 | read_only | bal = float(pdata.get('total_balance', 0) or 0) |
| 46827 | read_only | avail = float(pdata.get('available_balance', 0) or 0) |
| 46828 | read_only | m_used = float(pdata.get('total_margin_used', 0) or 0) |
| 46829 | read_only | unreal = float(pdata.get('unrealized_pnl', 0) or 0) |
| 46831 | read_only | pdata.get('margin_utilization_pct', pdata.get('margin_utilization', 0)) or 0 |
| 46833 | read_only | ts_raw = pdata.get('timestamp') or pdata.get('ts_ms') or 0 |
| 46860 | read_only | 'position_count': int(pdata.get('position_count', 0) or 0), |
| 46863 | read_only | 'data_source': 'trader_redis_per_account', |
| 46869 | read_only | bal = float(pdata.get('total_balance', 0) or 0) |
| 46870 | read_only | avail = float(pdata.get('available_balance', 0) or 0) |
| 46871 | read_only | m_used = float(pdata.get('total_margin_used', 0) or 0) |
| 46872 | read_only | unreal = float(pdata.get('unrealized_pnl', 0) or 0) |
| 46874 | read_only | pdata.get('margin_utilization_pct', pdata.get('margin_utilization', 0)) or 0 |
| 46876 | read_only | t_margin_bal = float(pdata.get('total_margin_balance', bal)) |
| 46877 | read_only | t_maint = float(pdata.get('total_maint_margin', 0.0)) |
| 46878 | read_only | ts_raw = pdata.get('timestamp') or pdata.get('ts_ms') or 0 |
| 46939 | read_only | 'data_source': 'trader_redis_multi_combined', |
| 46948 | write_metric | rc.hset(key, mapping={ |
| 46958 | write_metric | rc.set("portfolio:state:active_account", "primary", ex=120) |
| 46960 | read_only | logger.warning("⚠️ [PORTFOLIO] No portfolio data found in Redis or [REDACTED]; seeded fallback balances") |
| 47005 | write_metric | """Fetch latest equity snapshot published by traders. |
| 47011 | read_only | rc = self._signal_redis if getattr(self, "_signal_redis", None) is not None else get_redis() |
| 47071 | read_only | nested = obj.get("data") |
| 47083 | read_only | v = obj.get(k) |
| 47096 | read_only | v = obj.get(k) |
| 47107 | read_only | v = obj.get(k) |
| 47115 | read_only | ts = _normalize_ts(obj.get("timestamp") or obj.get("ts") or obj.get("ts_ms")) |
| 47116 | read_only | account = str(obj.get("account_id") or account_hint or "primary").strip().lower() |
| 47117 | read_only | mode = str(obj.get("mode") or "live") |
| 47135 | read_only | raw = rc.get(f"portfolio:equity:{aid}") |
| 47145 | read_only | raw = rc.get(key) |
| 47152 | read_only | ts = float(payload.get("timestamp", 0.0) or 0.0) |
| 47161 | read_only | active_account = rc.get("portfolio:state:active_account") |
| 47168 | read_only | state = rc.hgetall(state_key) |
| 47175 | read_only | ts = float(decoded.get("timestamp", 0.0) or 0.0) |
| 47178 | read_only | decoded.get("equity_usd") |
| 47179 | read_only | or decoded.get("total_balance") |
| 47180 | read_only | or decoded.get("equity") |
| 47184 | read_only | decoded.get("available_margin_usd") |
| 47185 | read_only | or decoded.get("available_balance") |
| 47186 | read_only | or decoded.get("available_margin") |
| 47190 | read_only | decoded.get("used_margin_usd") |
| 47191 | read_only | or decoded.get("total_margin_used") |
| 47196 | read_only | "mode": decoded.get("mode", "live"), |
| 47232 | read_only | rt_raw = self._signal_redis.get(f"price:realtime:{symbol}") |
| 47236 | read_only | rt_price = float(rt.get("price", 0) or 0) |
| 47237 | read_only | rt_ts = int(rt.get("ts_ms", 0) or 0) |
| 47246 | read_only | features = self._signal_redis.hgetall(key) |
| 47260 | read_only | market_data = self._signal_redis.get(market_key) |
| 47276 | read_only | features = self._signal_redis.hgetall(key) |
| 47290 | read_only | market_data = self._signal_redis.get(market_key) |
| 47305 | read_only | data = self._signal_redis.hgetall(key) |
| 47316 | read_only | latest_price = self._signal_redis.lindex(price_key, 0) |
| 47395 | read_only | # Get all open positions from Redis |
| 47396 | read_only | position_keys = self._signal_redis.keys("position:*") |
| 47418 | read_only | position_data = self._signal_redis.hgetall(key) |
| 47423 | read_only | has_position = position_data.get('has_position', b'false') |
| 47435 | read_only | pnl_pct = float(position_data.get('pnl_pct', 0)) |
| 47436 | read_only | age_seconds = float(position_data.get('age_seconds', 0)) |
| 47437 | read_only | side = position_data.get('side', b'UNKNOWN') |
| 47444 | read_only | _wp = self._signal_redis.hgetall(f"prediction:{symbol}:multi") |
| 47446 | read_only | _wpc = float((_wp.get(b"confidence") or _wp.get(b"model_confidence") or b"0.5").decode() if isinstance((_wp.get(b"confidence") or b"0.5"), bytes) else (_wp.get("confidence") or _wp.get("model_confidence") or 0.5)) |
| 47449 | read_only | _wp_dir = ((_wp.get(b"direction") or b"").decode() if isinstance(_wp.get(b"direction", b""), bytes) else str(_wp.get("direction", ""))).upper() |
| 47459 | read_only | signal_confidence = latest_signals[0].get('confidence', 0.5) |
| 47629 | read_only | pred = tf_map.get(tf, {"dir": "FLAT", "conf": 0.0}) |
| 47630 | read_only | tf_dir = str(pred.get("dir", "FLAT") or "FLAT") |
| 47631 | read_only | tf_conf = float(pred.get("conf", 0.0) or 0.0) |
| 47906 | read_only | if spoof_result.get('is_spoof', False): |
| 47907 | read_only | spoof_confidence = spoof_result.get('confidence', 0) |
| 47908 | read_only | spoof_direction = spoof_result.get('direction', 'unknown') |
| 47909 | read_only | spoof_reason = spoof_result.get('reason', 'Unknown pattern') |
| 47978 | write_signal | def _publish_decisions_with_reasoning(self, actions, confidences=None, prices=None, ts: float = None): |
| 47979 | write_metric | """Publish detailed decisions with position sizing and natural language reasoning""" |
| 47983 | write_signal | if not getattr(config, "PUBLISH_SIGNALS", True): |
| 48024 | write_signal | # SPECIAL HANDLING: If REBALANCE action, publish simplified rebalancing signal |
| 48036 | write_metric | "source": getattr(config, "PUBLISH_SOURCE_TAG", "trainer"), |
| 48039 | read_only | "bypass_gating": bool(contextual_action.get("bypass_gating", False)), |
| 48050 | write_signal | built = self._publish_signal_payload(rebalance_payload, contract_required=False) |
| 48054 | write_signal | logger.exception(f"Failed to publish rebalancing signal: {e}") |
| 48089 | write_metric | "source": getattr(config, "PUBLISH_SOURCE_TAG", "trainer"), |
| 48091 | read_only | "bypass_gating": bool(contextual_action.get("bypass_gating", False)), |
| 48137 | write_metric | # REBALANCE publishing above. |
| 48146 | read_only | avail = float(portfolio_state.get("available_balance", 0.0) or 0.0) |
| 48147 | read_only | pos_pct = float(payload.get("recommended_position_pct", 0.0) or 0.0) |
| 48153 | write_signal | built = self._publish_signal_payload(payload, contract_required=True) |
| 48162 | write_metric | logger.exception(f"Failed to publish decision for {sym}: {e}") |
| 48164 | write_signal | # Legacy publisher removed - all signals now use _publish_decisions_with_reasoning() |
| 48165 | write_signal | # which publishes to self.main_config.SIGNAL_OUTPUT_STREAM with position-aware reasoning |
| 48363 | read_only | # Get recent signals from Redis stream |
| 48380 | read_only | recent_signals = self._signal_redis.xrevrange(stream_name, count=num_samples) |
| 48389 | read_only | # Try bytes key first (Redis returns bytes by default) |
| 48392 | read_only | # Try string key (some Redis clients decode) |
| 48406 | read_only | symbol = signal.get("symbol", "UNKNOWN") |
| 48407 | read_only | timeframe = signal.get("timeframe", "UNKNOWN") |
| 48408 | read_only | action = signal.get("final_action") or signal.get("action_name") or signal.get("action", "UNKNOWN") |
| 48409 | read_only | confidence = float(signal.get("model_confidence", signal.get("confidence", 0.0)) or 0.0) |
| 48410 | read_only | model = signal.get("model", "UNKNOWN") |
| 48411 | read_only | trade_mode = signal.get("trade_mode", "-") |
| 48412 | read_only | ts_ms = int(signal.get("ts_ms") or 0) or int(str(msg_id).split("-", 1)[0]) |
| 48413 | read_only | account_id = signal.get("account_id") or acct_hint |
| 48482 | write_metric | self._feat_ts_seen = set() |
| 48507 | write_metric | self._feat_ts_seen = set() |
| 48646 | read_only | _v = _vals.get(_k) |
| 48661 | read_only | infos = self.locals.get("infos", []) if isinstance(self.locals, dict) else [] |
| 48662 | read_only | dones = self.locals.get("dones", []) if isinstance(self.locals, dict) else [] |
| 48671 | read_only | age_ms = int(info.get("features_age_ms", -1) or -1) |
| 48674 | read_only | hlen = int(info.get("features_hlen", 0) or 0) |
| 48677 | read_only | ts_ms = int(info.get("features_ts_ms", 0) or 0) |
| 48688 | read_only | realized = float(info.get('realized_pnl_usd', 0.0) or 0.0) |
| 48697 | read_only | self._env_raw_reward[idx] += float(info.get('raw_reward', 0.0)) |
| 48698 | read_only | self._env_risk_reward[idx] += float(info.get('risk_adjusted_reward', 0.0)) |
| 48701 | read_only | ep = info.get("episode") |
| 48704 | read_only | reward = ep.get('r', 0.0) |
| 48705 | read_only | length = ep.get('l', 0) |
| 48706 | read_only | drawdown = ep.get('max_drawdown', 0.0) |
| 48826 | read_only | if os.path.exists(masa_path): |
| 48876 | read_only | if os.path.exists(historical_baseline_path): |
| 48884 | read_only | model_state = checkpoint.get('model_state', checkpoint) |
| 48943 | read_only | if os.path.exists(masa_baseline_path): |
| 48947 | read_only | masa_state = masa_checkpoint.get('model_state_dict', masa_checkpoint) |
| 48978 | read_only | if checkpoint_metadata and checkpoint_metadata.get("ppo_checkpoint_path"): |
| 49032 | read_only | if os.path.exists(metadata_file): |
| 49036 | read_only | checkpoint_obs_dim = metadata.get('obs_dim') |
| 49080 | read_only | def create_env_target(): |
| 49096 | read_only | raise exception_queue.get() |
| 49100 | read_only | self.vec_env = result_queue.get() |
| 49108 | write_checkpoint_metadata | logger.info("💡 Old checkpoint may be incompatible - please delete old checkpoints or train fresh") |
| 49314 | read_only | - Redis clients |
| 49322 | write_metric | state.pop('_last_published_lock', None)     # Phase 3 |
| 49325 | read_only | state.pop('redis', None) |
| 49326 | read_only | state.pop('_signal_redis', None) |
| 49343 | write_metric | if not hasattr(self, '_last_published_lock'): |
| 49344 | write_metric | self._last_published_lock = threading.Lock() |
| 49427 | read_only | '_signal_redis',  # Redis clients |
| 49428 | read_only | '_redis', |
| 49429 | read_only | 'redis', |
| 49462 | read_only | policy_attrs = ['_signal_redis', '_redis', '_logger'] |
| 49505 | read_only | if not path or not path.exists(): |
| 49517 | read_only | if not path or not path.exists(): |
| 49569 | read_only | if final_path.exists(): |
| 49629 | read_only | #   1. Excluding known unpickleable attrs (_trainer, redis, etc.) |
| 49652 | read_only | if tmp_path.exists() and tmp_path.stat().st_size > 0: |
| 49657 | read_only | save_error = f"SB3 save produced empty file ({tmp_path.stat().st_size if tmp_path.exists() else 'missing'} bytes)" |
| 49689 | read_only | optimizer_sd = {'state': {}, 'param_groups': raw_opt_sd.get('param_groups', [])} |
| 49690 | read_only | for k, v in raw_opt_sd.get('state', {}).items(): |
| 49732 | read_only | if tmp_fallback.exists() and tmp_fallback.stat().st_size > 0: |
| 49742 | read_only | if not save_success or not ppo_path.exists() or ppo_path.stat().st_size == 0: |
| 49744 | write_metric | # Delete empty file to prevent confusion |
| 49745 | read_only | if ppo_path.exists() and ppo_path.stat().st_size == 0: |
| 49747 | write_checkpoint_metadata | logger.info(f"[CHECKPOINT_SAVE] Deleted empty checkpoint file") |
| 49855 | read_only | if tmp_latest.exists() and tmp_latest.stat().st_size > 0: |
| 49995 | read_only | raw = meta.get(key) |
| 50004 | read_only | if stable_zip.exists(): |
| 50014 | write_metric | seen = set() |
| 50031 | read_only | if latest.exists(): |
| 50036 | read_only | if not checkpoint_dir.exists(): |
| 50058 | read_only | if metadata.get('masa_path'): |
| 50063 | read_only | if masa_path.exists(): |
| 50141 | write_metric | last_publish_ms = 0 |
| 50143 | write_metric | with self._last_published_lock: |
| 50144 | write_metric | if self._last_published_ts: |
| 50145 | write_metric | last_publish_ms = max(self._last_published_ts.values()) |
| 50147 | write_metric | last_publish_ms = 0 |
| 50165 | write_metric | f"last_features_ts_ms={last_features_ts_ms} / last_publish_ms={last_publish_ms}" |
| 50180 | read_only | if getattr(self, "redis", None) is not None: |
| 50181 | write_metric | self.redis.hset( |
| 50194 | write_metric | "last_publish_ms": str(int(last_publish_ms or 0)), |
| 50197 | read_only | self.redis.expire("trainer:brain:status", 600) |
| 50216 | write_checkpoint_metadata | # Delete old checkpoints |
| 50222 | write_checkpoint_metadata | # Delete associated model files |
| 50223 | read_only | if metadata.get('ppo_path'): |
| 50225 | read_only | if ppo_path.exists(): |
| 50228 | read_only | if metadata.get('masa_path'): |
| 50230 | read_only | if masa_path.exists(): |
| 50233 | write_metric | # Delete metadata file |
| 50260 | write_signal | # Initialize signal publishing setup |
| 50261 | read_only | import redis |
| 50265 | read_only | self._signal_redis = redis.Redis(host='localhost', port=6379, decode_responses=True) |
| 50289 | read_only | if checkpoint_metadata and checkpoint_metadata.get("ppo_checkpoint_path"): |
| 50329 | read_only | ppo_path = ckpt.get("ppo_checkpoint_path") if ckpt else None |
| 50370 | write_metric | from utils.ensemble_diagnostics import publish_ensemble_diagnostic |
| 50371 | write_metric | from utils.decision_bus import publish_decision_record |
| 50387 | read_only | if not getattr(self, "_signal_redis", None): |
| 50390 | read_only | self._signal_redis.setex(self._heartbeat_key, 30, json.dumps(hb_payload)) |
| 50404 | write_signal | self._signal_redis.xadd( |
| 50407 | read_only | maxlen=getattr(self.main_config, "SIGNAL_STREAM_MAXLEN", 5000), |
| 50411 | write_heartbeat | logger.debug(f"[HEARTBEAT] stream publish failed: {hb_stream_err}") |
| 50413 | write_metric | # Diagnostic tap point: proves the live trainer process can publish diagnostics. |
| 50415 | write_metric | publish_ensemble_diagnostic({ |
| 50428 | write_heartbeat | logger.debug(f"[HEARTBEAT] diagnostic publish failed: {hb_diag_err}") |
| 50445 | write_metric | "training_active": bool(self.training_active.is_set()) if hasattr(self, "training_active") else False, |
| 50451 | read_only | decision_maxlen = int(getattr(self.main_config, "DECISION_STREAM_MAXLEN", 50000) or 50000) |
| 50452 | write_signal | tick_id = publish_decision_record(self._signal_redis, decision_tick, maxlen=decision_maxlen) |
| 50454 | write_heartbeat | logger.warning("[DECISION_TICK_FAIL] heartbeat decision tick publish returned None") |
| 50456 | write_heartbeat | logger.warning(f"[DECISION_TICK_FAIL] heartbeat decision tick publish error: {hb_tick_err}") |
| 50524 | read_only | rflags = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 50535 | read_only | redis_client=getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 50543 | write_metric | # Anti-churn: while PPO is actively training, do NOT publish |
| 50547 | read_only | hm_mode = str(sig.get("hedge_mode") or "").upper() |
| 50556 | read_only | if str(sig.get("action") or "").upper() == "FREE_MARGIN_FOR_HEDGE": |
| 50562 | write_signal | built = self._publish_signal_unified(ecf_sig, contract_required=True) |
| 50565 | write_signal | f"🚨 [ECF_V2] Published {built.get('symbol')} {built.get('action_name')} " |
| 50566 | read_only | f"acct={built.get('account_id')} reason=FREE_MARGIN_FOR:{sig.get('symbol')}" |
| 50569 | write_metric | logger.debug(f"[ECF_V2] publish failed: {ecf_pub_err}") |
| 50571 | write_metric | # Route through orchestrator during training (no direct publish) |
| 50572 | read_only | mode = str(sig.get("hedge_mode") or "").upper() |
| 50584 | read_only | f"🧠 [HEDGE_MGR_V3][TRAINING→ORCH] {sig.get('account_id')}:{sig.get('symbol')} " |
| 50585 | read_only | f"{sig.get('action')} mode={mode}" |
| 50588 | write_metric | logger.debug(f"[HEDGE_MGR_V3][TRAINING] publish failed: {pub_err}") |
| 50597 | write_metric | # Force immediate publish (no next-cycle delay) for flash hedges |
| 50600 | write_signal | built = self._publish_signal_unified(sig, contract_required=True) |
| 50603 | write_signal | f"⚡🛡️ [TRAINING_FASTLANE] Published {built.get('symbol')} {built.get('action_name')}" |
| 50606 | write_metric | logger.debug(f"[TRAINING_FASTLANE] publish failed: {pub_err}") |
| 50616 | write_signal | built = self._publish_signal_unified(sig, contract_required=True) |
| 50619 | write_signal | f"🛡️ [TRAINING_PROTECTIVE] Published {built.get('symbol')} {built.get('action_name')}" |
| 50622 | write_metric | logger.debug(f"[TRAINING_PROTECTIVE] hedge publish failed: {pub_err}") |
| 50633 | write_signal | built = self._publish_signal_unified(sig, contract_required=True) |
| 50636 | write_signal | f"⚡ [FRH_TRAINING] Published {built.get('symbol')} {built.get('action_name')} score={sig.get('reversal_score', 0):.2f}" |
| 50639 | write_metric | logger.debug(f"[FRH_TRAINING] publish failed: {pub_err}") |
| 50649 | write_signal | built = self._publish_signal_unified(sig, contract_required=True) |
| 50652 | write_signal | f"💰 [TRAINING_PROTECTIVE] Published {built.get('symbol')} {built.get('action_name')}" |
| 50655 | write_metric | logger.debug(f"[TRAINING_PROTECTIVE] profit publish failed: {pub_err}") |
| 50665 | write_signal | built = self._publish_signal_unified(sig, contract_required=True) |
| 50668 | write_signal | f"📈 [TRAINING_FAM] Published {built.get('symbol')} {built.get('action_name')}" |
| 50671 | write_metric | logger.debug(f"[TRAINING_FAM] add-margin publish failed: {pub_err}") |
| 50759 | write_signal | self._maybe_emit_canary(published_count=int(predictions_made or 0), cycle_count=cycle_count) |
| 50779 | write_signal | # Publish monitor signals to trader |
| 50782 | write_signal | built = self._publish_signal_unified(signal, contract_required=True) |
| 50784 | write_signal | logger.info(f"✅ Published monitor signal: {signal['symbol']} {signal['action']}") |
| 50786 | write_signal | logger.error(f"Failed to publish monitor signal: {pub_err}") |
| 50800 | read_only | rflags = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 50810 | read_only | hm = HedgeManagerV3(redis_client=getattr(self, "_signal_redis", None) or getattr(self, "redis", None)) |
| 50820 | read_only | mode = str(signal.get("hedge_mode") or "").upper() |
| 50833 | read_only | logger.info(f"📤 [HEDGE_MGR_V3→ORCH] {signal.get('account_id')}:{signal.get('symbol')} {signal.get('action')} mode={mode}") |
| 50854 | read_only | logger.info(f"📤 [HEDGE_BUILDER→ORCH] {signal.get('account_id')}:{signal['symbol']} {signal['action']}") |
| 50856 | write_signal | logger.error(f"Failed to publish hedge signal: {pub_err}") |
| 50875 | read_only | logger.info(f"⚡ [FRH→ORCH] {signal.get('account_id')}:{signal['symbol']} {signal['action']} score={signal.get('reversal_score', 0):.2f}") |
| 50877 | write_metric | logger.error(f"[FRH] publish failed: {pub_err}") |
| 50898 | read_only | logger.info(f"📤 [PROFIT→ORCH] {signal.get('account_id')}:{signal['symbol']} {signal['action']}") |
| 50907 | write_metric | # NO FALLBACK TO DIRECT PUBLISH. |
| 50913 | read_only | redis_client = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 50914 | read_only | self._urc = UnderwaterRecoveryController(redis_client=redis_client) |
| 50932 | read_only | logger.info(f"📤 [URC→ORCH] {signal.get('account_id')}:{signal.get('symbol')} {signal.get('action')}") |
| 50934 | read_only | logger.warning(f"❌ [URC] Failed to emit proposal (no fallback): {signal.get('symbol')}") |
| 50947 | read_only | redis_client = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 50948 | read_only | if redis_client: |
| 50952 | read_only | pb = ProfitBank(redis_client, account_id=str(aid)) |
| 50955 | read_only | if ing.get("credited_usd", 0.0) > 0: |
| 50957 | read_only | f"🏦 ProfitBank credit / acct={aid} +${ing.get('credited_usd', 0.0):.2f} " |
| 50958 | read_only | f"(processed={ing.get('processed', 0)})" |
| 50960 | read_only | if ing2.get("credited_usd", 0.0) > 0: |
| 50962 | read_only | f"🏦 ProfitBank PROFIT_EXIT credit / acct={aid} +${ing2.get('credited_usd', 0.0):.2f} " |
| 50963 | read_only | f"(processed={ing2.get('processed', 0)})" |
| 50971 | read_only | harvester = HedgeHarvestEngine(redis_client=redis_client) |
| 50976 | read_only | raw_map = redis_client.hgetall(f"portfolio:positions:{aid}") or {} |
| 50984 | write_metric | # publishing immediately. Here we confirm the hedge leg actually |
| 50985 | write_metric | # reduced (via portfolio:positions) before publishing an ADD_HEDGE_*. |
| 51000 | read_only | rflags = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 51013 | read_only | pend_keys = redis_client.lrange(qk, -50, -1) or [] |
| 51028 | read_only | pend_raw = redis_client.get(pend_key) |
| 51035 | read_only | sym0 = str(pend.get("symbol") or "").upper().strip() |
| 51036 | read_only | readd_side = str(pend.get("readd_side") or "").upper().strip() |
| 51037 | read_only | main_side0 = str(pend.get("main_side") or "").upper().strip() |
| 51041 | read_only | # Fetch current legs from the already-loaded raw_map (no extra redis calls). |
| 51044 | read_only | raw = raw_map.get(f"{sym0}:{side}") |
| 51058 | read_only | hedge_pos_now.get("margin_used", 0.0) |
| 51059 | read_only | or hedge_pos_now.get("initialMargin", 0.0) |
| 51065 | read_only | hedge_margin_pre = float(pend.get("hedge_margin_pre_usd", 0.0) or 0.0) |
| 51069 | read_only | close_fraction = float(pend.get("close_fraction", 0.0) or 0.0) |
| 51083 | read_only | main_pos_now.get("margin_used", 0.0) |
| 51084 | read_only | or main_pos_now.get("initialMargin", 0.0) |
| 51085 | read_only | or pend.get("main_margin_usd", 0.0) |
| 51089 | read_only | main_margin_now = float(pend.get("main_margin_usd", 0.0) or 0.0) |
| 51093 | read_only | target_ratio_eff = float(pend.get("target_ratio", HEDGE_TARGET_RATIO) or HEDGE_TARGET_RATIO) |
| 51104 | write_metric | redis_client.delete(pend_key) |
| 51105 | read_only | redis_client.lrem(qk, 0, pend_key) |
| 51127 | write_signal | built_rr = self._publish_signal_unified(readd_signal, contract_required=True) |
| 51134 | write_metric | redis_client.delete(pend_key) |
| 51135 | read_only | redis_client.lrem(qk, 0, pend_key) |
| 51138 | write_metric | # If publish fails, keep pending for next cycle (do not delete). |
| 51159 | read_only | sz = abs(float(pos.get("size", 0) or 0.0)) |
| 51169 | read_only | if not (legs.get("LONG") and legs.get("SHORT")): |
| 51176 | read_only | ha = redis_client.get(f"hedge:active:{sym}:{aid}") |
| 51180 | read_only | ms = str(ha.get("main_position_side") or "").upper() |
| 51181 | read_only | hs = str(ha.get("hedge_position_side") or "").upper() |
| 51189 | read_only | ln = float(legs["LONG"].get("notional", 0.0) or legs["LONG"].get("size_usd", 0.0) or 0.0) |
| 51193 | read_only | sn = float(legs["SHORT"].get("notional", 0.0) or legs["SHORT"].get("size_usd", 0.0) or 0.0) |
| 51203 | read_only | return float(p.get("roi_pct", 0.0) or p.get("pnl_pct", 0.0) or 0.0) |
| 51207 | read_only | main_roe = _roe(legs.get(main_side) or {}) |
| 51208 | read_only | hedge_roe = _roe(legs.get(hedge_side) or {}) |
| 51213 | read_only | n = float(p.get("notional", 0.0) or 0.0) |
| 51217 | read_only | sz = abs(float(p.get("size", 0.0) or 0.0)) |
| 51218 | read_only | px = float(p.get("current_price", 0.0) or p.get("mark_price", 0.0) or p.get("entry_price", 0.0) or 0.0) |
| 51222 | read_only | margin = float(p.get("margin_used", 0.0) or p.get("initialMargin", 0.0) or 0.0) |
| 51223 | read_only | lev = float(p.get("leverage", 1.0) or 1.0) |
| 51230 | read_only | mn = _calc_notional(legs.get(main_side) or {}) |
| 51231 | read_only | hn = _calc_notional(legs.get(hedge_side) or {}) |
| 51237 | read_only | st_raw = redis_client.get(f"urc:state:{aid}:{sym}") |
| 51241 | read_only | target = float(stj.get("min_ratio", stj.get("min_hedge_ratio", target)) or target) |
| 51249 | read_only | _hp = self._signal_redis.hgetall(f"prediction:{sym}:multi") |
| 51251 | read_only | _hpc = float((_hp.get(b"confidence") or _hp.get(b"model_confidence") or b"0").decode() if isinstance((_hp.get(b"confidence") or b"0"), bytes) else (_hp.get("confidence") or _hp.get("model_confidence") or 0)) |
| 51265 | read_only | fast = float(micro_h.get("fast_move_score", 0.0) or micro_h.get("flash_score", 0.0) or 0.0) |
| 51269 | read_only | churn = float(micro_h.get("churn_score", 0.0) or 0.0) |
| 51273 | read_only | snap = float(micro_h.get("snapback_score", 0.0) or 0.0) |
| 51277 | read_only | spoof = float(micro_h.get("spoof_score", 0.0) or 0.0) |
| 51281 | read_only | imb = float(micro_h.get("imbalance_5", 0.0) or 0.0) |
| 51318 | write_signal | built = self._publish_signal_unified(sig, contract_required=True) |
| 51321 | write_metric | f"💰 HedgeHarvest published / acct={aid} {sym} close={dec.close_side} " |
| 51345 | read_only | rflags = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 51361 | read_only | main_pos = legs.get(main_side) or {} |
| 51362 | read_only | hedge_pos = legs.get(hedge_side) or {} |
| 51363 | read_only | main_margin = float(main_pos.get("margin_used", 0) or main_pos.get("initialMargin", 0) or 0) |
| 51364 | read_only | hedge_margin_now = float(hedge_pos.get("margin_used", 0) or hedge_pos.get("initialMargin", 0) or 0) |
| 51374 | read_only | cont = float((micro_h or {}).get("continuation_risk", (micro_h or {}).get("continuation_score", 0.0)) or 0.0) |
| 51397 | write_metric | # Record pending re-add (best-effort). Do NOT publish immediately. |
| 51418 | read_only | redis_client.setex( |
| 51426 | write_metric | redis_client.rpush(qk, pend_key) |
| 51427 | read_only | redis_client.expire(qk, int(max(120, float(HEDGE_READD_PENDING_TTL_SECONDS or 600) + 60))) |
| 51429 | read_only | redis_client.ltrim(qk, -500, -1) |
| 51439 | write_metric | # Legacy: immediate re-add publish |
| 51455 | write_signal | readd_built = self._publish_signal_unified(readd_signal, contract_required=True) |
| 51458 | write_signal | f"🔄 [HEDGE_READD] Published / {aid}:{sym} {readd_action} " |
| 51469 | write_metric | # Publishes suggestions to Redis for operator visibility; can optionally execute trades |
| 51477 | read_only | redis_client = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 51478 | read_only | self._pra = PortfolioRecoveryAllocator(redis_client=redis_client) |
| 51486 | write_metric | self._pra.maybe_publish_suggestions(accounts=("primary", "asjad"), universe=universe) |
| 51505 | write_signal | built = self._publish_signal_unified(sig, contract_required=True) |
| 51508 | write_signal | f"🧭 [PRA_EXECUTE] Published {built.get('symbol')} {built.get('action_name')} " |
| 51509 | read_only | f"acct={built.get('account_id')} conf={built.get('confidence', 0):.3f}" |
| 51512 | write_metric | logger.debug(f"[PRA_EXECUTE] publish failed: {pub_err}") |
| 51527 | write_signal | built = self._publish_signal_unified(signal, contract_required=True) |
| 51529 | write_signal | logger.info(f"✅ Published flash hedge signal: {signal['symbol']} {signal['action']}") |
| 51531 | write_signal | logger.error(f"Failed to publish flash hedge signal: {pub_err}") |
| 51540 | write_signal | built = self._publish_signal_unified(fam_sig, contract_required=True) |
| 51542 | write_signal | logger.info(f"📈 [FAM] Published add-margin: {fam_sig['symbol']} {fam_sig['action']}") |
| 51544 | write_metric | logger.debug(f"[FAM] publish failed: {pub_err}") |
| 51631 | write_signal | # Initialize Redis connection for signal publishing |
| 51632 | read_only | import redis |
| 51636 | read_only | self._signal_redis = redis.Redis(host='localhost', port=6379, decode_responses=True) |
| 51639 | write_signal | # Initialize environment mapping for signal publishing |
| 51739 | read_only | redis_client = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 51740 | read_only | if not redis_client: |
| 51749 | read_only | def _safe_json_get(key: str, field: str) -> Optional[int]: |
| 51751 | read_only | raw = redis_client.get(key) |
| 51758 | read_only | return _safe_int(obj.get(field)) |
| 51764 | read_only | ob_ts = _safe_int(redis_client.get(f"heartbeat:OrderBook:{symbol}")) |
| 51771 | read_only | mk_ts = _safe_json_get(f"latest:[REDACTED]:mark_price:{symbol}", "ts_ms") |
| 51778 | read_only | uf = redis_client.hgetall(f"unified_features:{symbol}:{timeframe}") or {} |
| 51786 | read_only | liq_updated_ts = _safe_int(uf.get("liquidation_updated_ts")) |
| 51793 | read_only | oi_ts = _safe_json_get(f"latest:[REDACTED]:open_interest:{symbol}:{timeframe}", "ts_ms") |
| 51800 | read_only | trades_ts = _safe_json_get(f"latest:[REDACTED]:market_order_flow:{symbol}:{timeframe}", "ts_ms") |
| 51807 | read_only | if ages.get("liq_age_ms") is None: |
| 51809 | read_only | liq_ts = _safe_json_get(f"latest:[REDACTED]:liquidations:{symbol}:{timeframe}", "ts_ms") |
| 51846 | read_only | sym_hist = list(hist.get(symbol, [])) |
| 51851 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 51853 | read_only | ob_raw = rc.get(f"orderbook:top:{symbol}") |
| 51858 | read_only | bid = float(ob.get("bid", 0) or 0) |
| 51859 | read_only | ask = float(ob.get("ask", 0) or 0) |
| 51860 | read_only | ts_ms = int(ob.get("ts", 0) or 0) |
| 51864 | read_only | mk_raw = rc.get(f"latest:[REDACTED]:mark_price:{symbol}") |
| 51869 | read_only | mk_ts = int(mk.get("ts_ms", 0) or 0) |
| 51870 | read_only | mk_price = float(mk.get("mark_price", 0) or 0) |
| 51900 | read_only | def _fget(prefixes: List[str]) -> Optional[float]: |
| 51904 | read_only | return float(feature_dict.get(k)) |
| 51912 | read_only | rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 51916 | read_only | raw = rc.get(key) |
| 51923 | read_only | ts_ms = obj.get("ts_ms") |
| 51944 | read_only | buy = _fget([ |
| 51949 | read_only | sell = _fget([ |
| 51958 | read_only | ob_imb = _fget([ |
| 51963 | read_only | short_liq = _fget([ |
| 51967 | read_only | long_liq = _fget([ |
| 51990 | read_only | until_ms = int(override_key.get(symbol, 0) or 0) |
| 52025 | write_metric | 't_publish': 0.0, |
| 52043 | read_only | redis_client = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 52044 | read_only | if redis_client: |
| 52047 | read_only | pb = ProfitBank(redis_client, account_id=str(aid)) |
| 52082 | write_metric | "published": 0, |
| 52095 | write_risk_state | self._why_no_open_risk_cycle_published_open_risk = set() |
| 52122 | read_only | # 1) Dependency gate - Redis client |
| 52123 | write_signal | if getattr(self, "_signal_redis", None) is None or not hasattr(getattr(self, "_signal_redis", None), "xadd"): |
| 52124 | read_only | from utils.redis_client import get_redis |
| 52125 | read_only | self._signal_redis = get_redis() |
| 52126 | read_only | logger.info("🔧 [PREDICT] Reinitialized Redis client in prediction thread") |
| 52129 | write_signal | if not hasattr(self, '_signal_redis') or not hasattr(self._signal_redis, "xadd"): |
| 52130 | read_only | exit_reason = "no_redis_client" |
| 52154 | write_signal | # "immediate" = publish all signals immediately, trader handles deconfliction |
| 52160 | write_metric | # If mode is "immediate", we publish directly without buffering |
| 52165 | write_metric | logger.debug("[C2] Immediate publish mode - deconfliction handled by trader") |
| 52179 | read_only | logger.debug("[DEBUG] Getting feature sets from Redis using known symbol list...") |
| 52181 | read_only | # DYNAMIC SYMBOL REFRESH: Check for symbol updates from Redis |
| 52186 | write_metric | if refreshed_symbols and set(refreshed_symbols) != set(SYMBOLS): |
| 52256 | read_only | # Ensure Redis is available before batch processing |
| 52257 | read_only | if getattr(self, '_signal_redis', None) is None: |
| 52259 | read_only | from utils.redis_client import get_redis |
| 52260 | read_only | self._signal_redis = get_redis() |
| 52261 | read_only | logger.info("[GPU_BATCH] Redis connection established") |
| 52262 | read_only | except Exception as redis_err: |
| 52263 | read_only | logger.warning(f"[GPU_BATCH] Redis init failed: {redis_err}, falling back to legacy path") |
| 52295 | read_only | # IMPORTANT (perf): Don't hit Redis for trader positions on every (symbol,tf). |
| 52325 | read_only | features = self._signal_redis.hgetall(feature_key) |
| 52340 | read_only | ts_ms = int(decoded_features.get('ts_ms', 0)) |
| 52345 | read_only | threshold = FRESHNESS_THRESHOLDS.get(timeframe, 300000) |
| 52370 | read_only | pos_size = float(pos.get('size', 0) or 0) |
| 52373 | read_only | position_pnl_pct = float(pos.get('pnl_percentage', 0) or pos.get('unrealized_pnl_pct', 0) or 0) |
| 52374 | read_only | open_time = pos.get('open_time') or pos.get('entry_ts') |
| 52416 | write_metric | # Prefer trader-published per-account portfolio snapshot (fast + accurate for live) |
| 52424 | read_only | total_equity = float(st.get("total_balance", 0.0) or 0.0) |
| 52425 | read_only | total_unrealized = float(st.get("unrealized_pnl", 0.0) or 0.0) |
| 52426 | read_only | margin_ratio = float(st.get("margin_utilization_pct", 0.0) or 0.0) |
| 52427 | read_only | position_count = int(st.get("position_count", 0) or 0) |
| 52430 | read_only | realized_pnl_1d = float(st.get("realized_pnl_1d", 0.0) or 0.0) |
| 52431 | read_only | realized_pnl_7d = float(st.get("realized_pnl_7d", 0.0) or 0.0) |
| 52465 | read_only | _btc_corr_redis = ( |
| 52466 | read_only | getattr(self, "_signal_redis", None) |
| 52467 | read_only | or getattr(self, "redis", None) |
| 52469 | read_only | if _btc_corr_redis: |
| 52471 | read_only | decoded_features, _btc_corr_redis, symbol, tf=timeframe, |
| 52527 | read_only | feature_tensor[_bi, _obs_dim - 5] = _tf_ordinal_map.get(_tf, 0.5) |
| 52533 | read_only | _side_val = float(_fdict.get('position_side_encoding', 0.0) or 0.0) |
| 52534 | read_only | _pnl_pct = float(_fdict.get('position_pnl_pct', 0.0) or 0.0) |
| 52579 | read_only | c_raw = p.get("confidence", p.get("model_confidence")) |
| 52593 | read_only | c = p.get("confidence", p.get("model_confidence")) |
| 52607 | write_metric | publish_debug = bool(int(os.getenv("PUBLISH_DEBUG", "1"))) |
| 52618 | read_only | _hold_count = sum(1 for p in cleaned_predictions if str(p.get("action") or p.get("action_name") or "").upper() in ("HOLD", "NO_ACTION", "NONE")) |
| 52620 | write_metric | if publish_debug: |
| 52625 | write_signal | n_pub = self._publish_batch_predictions( |
| 52628 | write_metric | debug=publish_debug, |
| 52635 | read_only | conf_values = [p.get("model_confidence", 0.0) for p in cleaned_predictions] |
| 52636 | read_only | ppo_values = [p.get("ppo_confidence", 0.0) for p in cleaned_predictions] |
| 52637 | read_only | masa_values = [p.get("masa_confidence", 0.0) for p in cleaned_predictions] |
| 52642 | write_signal | f"[GPU_BATCH] Published {n_pub} signals (validated={len(cleaned_predictions)})" |
| 52711 | read_only | # Get features from Redis (with None check for safety) |
| 52712 | read_only | if not self._signal_redis: |
| 52713 | read_only | logger.debug(f"[PREDICT] Skipping {symbol}:{timeframe} - Redis client not initialized") |
| 52716 | read_only | features = self._signal_redis.hgetall(feature_key) |
| 52725 | read_only | # Decode bytes if needed (Redis sometimes returns bytes) |
| 52739 | read_only | ts_ms = int(decoded_features.get('ts_ms', 0)) |
| 52744 | read_only | threshold = FRESHNESS_THRESHOLDS.get(timeframe, 300000)  # Default to 5min if TF unknown |
| 52764 | write_metric | suppress_publish=True, |
| 52770 | write_metric | # Legacy mode: immediate per-TF publish |
| 52776 | write_metric | suppress_publish=False, |
| 52781 | write_signal | logger.debug(f"{symbol}:{timeframe} - Signal published (total: {produced})") |
| 52818 | read_only | _dc_sym = str(_dc_payload.get("symbol", "")).strip() |
| 52822 | read_only | _dc_payload.get("action_name") |
| 52823 | read_only | or _dc_payload.get("action") |
| 52824 | read_only | or _dc_payload.get("predicted_action") |
| 52831 | read_only | _dc_payload.get("model_confidence") |
| 52832 | read_only | or _dc_payload.get("confidence") |
| 52837 | read_only | _dc_payload.get("ppo_confidence") |
| 52838 | read_only | or _dc_payload.get("ppo_conf") |
| 52842 | read_only | _dc_payload.get("price_target") |
| 52843 | read_only | or _dc_payload.get("target_price") |
| 52844 | read_only | or _dc_payload.get("trainer_target_price") |
| 52847 | read_only | _dc_target_pct = str(_dc_payload.get("price_target_pct") or "") |
| 52848 | read_only | _dc_target_dir = str(_dc_payload.get("price_target_direction") or _dc_dir) |
| 52852 | read_only | _px_raw = self._signal_redis.get(f"price:{_dc_sym}") |
| 52857 | read_only | _dc_cpx = float(_json_dc.loads(_px_s).get("price", 0) or 0) |
| 52864 | read_only | _natr_dc = _lookup_natr_atr_pct(self._signal_redis, _dc_sym) |
| 52865 | read_only | _dc_tf_src = str(_dc_payload.get("timeframe") or "5m") |
| 52866 | read_only | _pt_dc = _compute_price_target( |
| 52872 | read_only | _dc_target = float(_pt_dc.get("price_target", 0.0)) |
| 52873 | read_only | _dc_target_pct = str(_pt_dc.get("price_target_pct", "")) |
| 52874 | read_only | _dc_target_dir = str(_pt_dc.get("price_target_direction", _dc_dir)) |
| 52893 | write_metric | "published": "1", |
| 52896 | write_signal | self._signal_redis.hset(_dc_pred_key, mapping=_dc_pred_map) |
| 52897 | read_only | self._signal_redis.expire(_dc_pred_key, 1800) |
| 52904 | write_signal | logger.info(f"[DECONFLICT] Step 3/4: After position check: {len(final)} signals to publish") |
| 52929 | write_metric | active_symbols = list(set(sig.get('symbol') for sig in final if sig.get('symbol'))) |
| 52951 | write_signal | # Step 4: Publish deconflicted signals |
| 52952 | write_metric | t_publish_start = time.perf_counter() |
| 52954 | write_signal | predictions_made = self._publish_buffered_signals(final) |
| 52956 | write_signal | dbg["published"] += predictions_made  # Fix: count deconflicted publishes in DECISION_FUNNEL |
| 52957 | write_signal | logger.info(f"[DECONFLICT] Step 4/4: Published {predictions_made} deconflicted signals ✅") |
| 52959 | write_signal | logger.info(f"[DECONFLICT] Step 4/4: No signals to publish after deconfliction 📭") |
| 52960 | write_metric | timing['t_publish'] = time.perf_counter() - t_publish_start |
| 52963 | write_signal | _open_risk_published = sum(1 for s in (final or []) if s.get('action_category') == 'OPEN_RISK') if predictions_made > 0 else 0 |
| 52964 | write_risk_state | if _open_risk_published == 0: |
| 52967 | write_signal | self._adaptive_zero_signal_count = 0  # Reset on any successful publish |
| 52982 | write_signal | f"📊 Prediction batch #{self._prediction_batch_count}: {len(feature_keys)} symbols processed, {predictions_made} signals published (total: {self._prediction_total_count})" |
| 52994 | read_only | _breadth_redis = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 52996 | read_only | if (_breadth_enabled or _rba_enabled or _reversal_enabled) and _breadth_redis: |
| 53009 | read_only | from risk.market_regime import compute_regime_from_redis |
| 53010 | read_only | _regime_redis = _breadth_redis |
| 53016 | read_only | _existing_ttl = _regime_redis.ttl(f"regime:{_rsym}") |
| 53020 | read_only | _rg = compute_regime_from_redis( |
| 53021 | read_only | _regime_redis, _rsym, |
| 53041 | read_only | _breadth_redis, symbols=_breadth_syms, timeframe=_btf, |
| 53047 | read_only | _primary_breadth = _breadth_results.get("5m") or _breadth_results.get("15m") or {} |
| 53053 | read_only | _primary_breadth.get("breadth_dir", 0), |
| 53054 | read_only | _primary_breadth.get("breadth_strength", 0), |
| 53055 | read_only | _primary_breadth.get("breadth_entropy", 1), |
| 53056 | read_only | _primary_breadth.get("breadth_corr", 0), |
| 53057 | read_only | _primary_breadth.get("breadth_vol", 0), |
| 53058 | read_only | _primary_breadth.get("breadth_fast_move", 0), |
| 53059 | read_only | _primary_breadth.get("n_symbols_fresh", 0), |
| 53060 | read_only | _primary_breadth.get("n_long", 0), |
| 53061 | read_only | _primary_breadth.get("n_neutral", 0), |
| 53062 | read_only | _primary_breadth.get("n_short", 0), |
| 53074 | read_only | _rba_move_regime = str(_primary_breadth.get("breadth_fast_move", 0.0)) |
| 53082 | read_only | _rr = _breadth_redis.get(f"regime:{_rsym}") |
| 53085 | read_only | _regime_move_regimes.append(str(_rrd.get("move_regime", "NORMAL"))) |
| 53086 | read_only | _regime_liq_risks.append(float(_rrd.get("liq_risk", 0) or 0)) |
| 53103 | read_only | _rba_mu = float(_rba_st.get("margin_utilization_pct", 0) or 0) |
| 53104 | read_only | _rba_eq = float(_rba_st.get("total_balance", 0) or 0) |
| 53107 | read_only | _stress_raw = _breadth_redis.get(f"orch:portfolio_stress:{_rba_acct}") |
| 53111 | read_only | _rba_stress = bool(_stress_data.get("active", False)) |
| 53115 | read_only | _alloc = compute_risk_budget( |
| 53121 | read_only | fast_move_score=float(_primary_breadth.get("breadth_fast_move", 0)), |
| 53133 | read_only | cache_allocation(_breadth_redis, _rba_acct, _alloc, ttl_sec=300) |
| 53154 | read_only | cache_reversal_state(_breadth_redis, self._reversal_state, ttl_sec=300) |
| 53172 | read_only | _breadth_redis, account_id=_msc_acct, |
| 53175 | read_only | cache_market_state_contract(_breadth_redis, _msc) |
| 53190 | read_only | from risk.microstructure_toxicity import compute_toxicity_from_redis |
| 53195 | read_only | _tr = compute_toxicity_from_redis(_breadth_redis, _tox_sym, "5m") |
| 53218 | write_risk_state | "[PREDICT] SUMMARY total=%d no_feat=%d nan=%d low=%d hold=%d cooldown=%d dupe=%d pos=%d regime=%d published=%d", |
| 53220 | write_risk_state | dbg["cooldown"], dbg["dupe_suppressed"], dbg["pos_blocked"], dbg["regime_blocked"], dbg["published"] |
| 53227 | read_only | _vctr_redis = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 53228 | read_only | if _vctr_redis is not None: |
| 53232 | read_only | _wma_len = int(_vctr_redis.xlen("wma:proposals") or 0) |
| 53239 | read_only | _pos_primary = len([f for f in (_vctr_redis.hkeys("portfolio:positions:primary") or []) if b":LONG" in f or ":LONG" in str(f) or b":SHORT" in f or ":SHORT" in str(f)]) |
| 53243 | read_only | _pos_asjad = len([f for f in (_vctr_redis.hkeys("portfolio:positions:asjad") or []) if b":LONG" in f or ":LONG" in str(f) or b":SHORT" in f or ":SHORT" in str(f)]) |
| 53247 | write_metric | "CYCLE_INTENTS rl_published=%d proposals_pending=%d " |
| 53249 | write_metric | int(dbg.get("published", 0)), |
| 53258 | read_only | # Persist the most recent prediction-cycle summary to Redis so operators can confirm |
| 53261 | read_only | _telemetry_redis = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 53262 | read_only | if _telemetry_redis is not None and hasattr(_telemetry_redis, "setex"): |
| 53270 | read_only | "total_checked": int(dbg.get("total_checked", 0)), |
| 53271 | read_only | "no_features": int(dbg.get("no_features", 0)), |
| 53272 | read_only | "nan_conf": int(dbg.get("nan_conf", 0)), |
| 53273 | read_only | "low_conf": int(dbg.get("low_conf", 0)), |
| 53274 | read_only | "hold": int(dbg.get("hold", 0)), |
| 53275 | read_only | "cooldown": int(dbg.get("cooldown", 0)), |
| 53276 | read_only | "dupe_suppressed": int(dbg.get("dupe_suppressed", 0)), |
| 53277 | read_only | "pos_blocked": int(dbg.get("pos_blocked", 0)), |
| 53278 | read_only | "regime_blocked": int(dbg.get("regime_blocked", 0)), |
| 53279 | write_metric | "published": int(dbg.get("published", 0)), |
| 53291 | read_only | # TTL keeps Redis clean if trainer stops. |
| 53292 | read_only | _telemetry_redis.setex( |
| 53307 | read_only | if dbg.get("low_conf", 0) > 0: |
| 53309 | read_only | if dbg.get("nan_conf", 0) > 0: |
| 53311 | read_only | if dbg.get("cooldown", 0) > 0: |
| 53313 | read_only | if dbg.get("dupe_suppressed", 0) > 0: |
| 53315 | read_only | if dbg.get("pos_blocked", 0) > 0: |
| 53317 | read_only | if dbg.get("regime_blocked", 0) > 0: |
| 53319 | read_only | if dbg.get("no_features", 0) > 0: |
| 53324 | write_metric | blocked_by["safe_mode"] = dbg["total_checked"] - dbg.get("hold", 0) - dbg.get("published", 0) |
| 53328 | read_only | f"considered={dbg['total_checked']} / hold={dbg.get('hold', 0)} / " |
| 53330 | write_signal | f"deconflicted={predictions_made} / published={dbg['published']} / " |
| 53335 | write_metric | # Optionally XADD to debug stream |
| 53338 | read_only | if self._signal_redis and DECISION_FUNNEL_DEBUG_STREAM: |
| 53339 | write_signal | self._signal_redis.xadd( |
| 53344 | read_only | "hold": str(dbg.get('hold', 0)), |
| 53345 | write_metric | "published": str(dbg['published']), |
| 53349 | read_only | maxlen=1000, |
| 53352 | write_metric | except Exception as xadd_err: |
| 53353 | write_metric | logger.debug(f"[DECISION_FUNNEL] XADD failed: {xadd_err}") |
| 53376 | write_metric | overlay_intents_published = 0 |
| 53384 | read_only | redis_client=self._signal_redis, |
| 53404 | read_only | active_count = sum(1 for p in all_positions.values() if abs(float(p.get('positionAmt', 0) or p.get('size', 0) or p.get('qty', 0) or 0)) > 1e-9) |
| 53410 | read_only | pos_amt = float(pos.get('positionAmt', 0) or pos.get('size', 0) or pos.get('qty', 0) or 0) |
| 53415 | read_only | pos_side = str(pos.get('side', '') or pos.get('positionSide', '') or 'UNKNOWN').upper() |
| 53424 | read_only | pos.get("symbol") |
| 53425 | read_only | or pos.get("s") |
| 53440 | read_only | pos.get("account_id") |
| 53441 | read_only | or pos.get("account") |
| 53442 | read_only | or pos.get("source") |
| 53443 | read_only | or pos.get("target_account_id") |
| 53453 | read_only | entry_price = float(pos.get('entryPrice', 0) or pos.get('entry_price', 0) or 0) |
| 53454 | read_only | mark_price = float(pos.get('markPrice', 0) or pos.get('mark_price', 0) or 0) |
| 53460 | read_only | lev_raw = pos.get('leverage', None) |
| 53469 | write_metric | # (this is what traders publish and is the ground truth for hedge-mode multi-account). |
| 53471 | read_only | redis_client = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 53472 | read_only | if redis_client and float(leverage) <= 1.01: |
| 53476 | read_only | raw_leg = redis_client.hget(f"portfolio:positions:{aid}", f"{clean_symbol}:{pos_side}") |
| 53482 | read_only | lev2 = leg.get("leverage") |
| 53524 | read_only | edge_gate = get_adaptive_edge_gate(redis_client=self._signal_redis) |
| 53565 | read_only | _mom_flag2 = self._signal_redis.get(f"wma:momentum_regime:{clean_symbol}") |
| 53585 | read_only | self._signal_redis.setex(ride_key, _ride_ttl2, json.dumps(ride_data)) |
| 53608 | write_metric | # ALWAYS publish to overlay:intents for observability |
| 53610 | write_metric | from utils.ensemble_diagnostics import publish_ensemble_diagnostic |
| 53615 | write_signal | from utils.signal_publish import publish_overlay_intent |
| 53616 | write_metric | publish_overlay_intent( |
| 53617 | read_only | self._signal_redis, |
| 53620 | read_only | maxlen=5000, |
| 53626 | read_only | did = f"{intent_data.get('ts_ms', int(time.time()*1000))}-{clean_symbol}-overlay-{str(self._resolve_target_account() or 'primary').lower()}" |
| 53627 | write_metric | publish_ensemble_diagnostic({ |
| 53631 | read_only | "tf": str(intent_data.get("timeframe") or intent_data.get("tf") or "overlay"), |
| 53632 | read_only | "action": str(intent_data.get("action") or intent_data.get("action_name") or "UNKNOWN"), |
| 53633 | read_only | "confidence": float(intent_data.get("confidence") or 0.0), |
| 53637 | write_metric | logger.debug(f"[OVERLAY] diagnostic publish failed: {overlay_diag_err}") |
| 53639 | write_metric | overlay_intents_published += 1 |
| 53642 | write_metric | except Exception as xadd_err: |
| 53643 | write_metric | logger.debug(f"[OVERLAY] Failed to publish intent: {xadd_err}") |
| 53648 | write_metric | self._publish_skip_event( |
| 53699 | write_signal | # Build and publish trading signal |
| 53702 | write_signal | built = self._publish_signal_payload( |
| 53714 | read_only | # Track in Redis sorted set for rate monitoring |
| 53717 | write_signal | self._signal_redis.zadd( |
| 53725 | write_signal | logger.debug(f"OVERLAY_EXECUTE_BLOCK / {symbol} / {intent.action.value} / reason=PUBLISH_FAILED") |
| 53728 | write_metric | self._publish_skip_event( |
| 53736 | write_metric | self._publish_skip_event( |
| 53745 | write_metric | if overlay_intents_published > 0 or overlay_executed > 0: |
| 53747 | write_metric | f"OVERLAY_CYCLE / intents={overlay_intents_published} / executed={overlay_executed} / blocked={overlay_blocked}" |
| 53751 | read_only | # OVERLAY RATE TRACKING: Per-symbol 10-minute rolling counter in Redis |
| 53757 | read_only | # Track overlay actions per symbol in Redis sorted set |
| 53762 | read_only | self._signal_redis.zremrangebyscore(zset_key, 0, cutoff_ms) |
| 53765 | read_only | self._signal_redis.expire(zset_key, 900) |
| 53778 | read_only | count = self._signal_redis.zcount(zset_key, cutoff_ms, now_ms) |
| 53817 | read_only | target_notional = hedge_signal.get('target_notional', 0) |
| 53822 | read_only | equity = float(portfolio.get('total_balance', 0) or 0) |
| 53840 | read_only | sym_cfg = SYMBOL_LEVERAGE_CONFIG.get(symbol, {}) or {} |
| 53841 | read_only | leverage = int(float(sym_cfg.get("max_leverage", 20) or 20)) |
| 53859 | write_signal | # Publish hedge signals to the trading stream |
| 53896 | write_signal | built = self._publish_signal_payload(payload, stream=stream, contract_required=True) |
| 53899 | write_metric | dbg["published"] += 1 |
| 53900 | write_signal | logger.info(f"🛡️ Published hedge signal: {symbol} → {hedge_signal['action']} margin=${margin_usd:.2f}") |
| 53903 | write_signal | logger.warning(f"⚠️ Failed to publish hedge signal for {hedge_signal['symbol']}: {e}") |
| 53909 | write_signal | # CANARY: Prove publishing path works if no normal signals (disabled by default) |
| 53914 | write_risk_state | "[PREDICT_ZERO] produced=0 / checked=%s no_features=%s nan_conf=%s low_conf=%s hold=%s cooldown=%s dupe=%s pos_blocked=%s regime_blocked=%s published=%s / " |
| 53916 | read_only | dbg.get("total_checked"), |
| 53917 | read_only | dbg.get("no_features"), |
| 53918 | read_only | dbg.get("nan_conf"), |
| 53919 | read_only | dbg.get("low_conf"), |
| 53920 | read_only | dbg.get("hold"), |
| 53921 | read_only | dbg.get("cooldown"), |
| 53922 | read_only | dbg.get("dupe_suppressed"), |
| 53923 | read_only | dbg.get("pos_blocked"), |
| 53924 | read_only | dbg.get("regime_blocked"), |
| 53925 | write_metric | dbg.get("published"), |
| 53933 | write_metric | if dbg["published"] == 0 and getattr(self.main_config, "ENABLE_CANARY_PUBLISH", False): |
| 53946 | write_signal | built = self._publish_signal_payload(payload, stream=stream, contract_required=False) |
| 53948 | write_metric | logger.info(f"[PREDICT] Canary published → {stream}") |
| 53950 | write_metric | logger.warning(f"[PREDICT] Canary publish failed: {e}") |
| 53982 | read_only | f"t_fetch={timing.get('t_fetch', 0):.3f} / t_infer={timing.get('t_infer', 0):.3f} / " |
| 53983 | write_metric | f"t_deconflict={timing.get('t_deconflict', 0):.3f} / t_publish={timing.get('t_publish', 0):.3f} / " |
| 53984 | read_only | f"t_overlay={timing.get('t_overlay', 0):.3f} / t_total={t_total:.3f} / " |
| 53988 | write_metric | # Periodic accuracy evaluation (runs every ~60s regardless of publish activity) |
| 54009 | read_only | ages.get("ob_age_ms"), |
| 54010 | read_only | ages.get("trades_age_ms"), |
| 54011 | read_only | ages.get("oi_age_ms"), |
| 54012 | read_only | ages.get("liq_age_ms"), |
| 54013 | read_only | ages.get("mark_age_ms"), |
| 54014 | read_only | ages.get("max_feature_age_ms"), |
| 54021 | read_only | # reach the trader. Check the Redis heartbeat key every cycle. |
| 54024 | read_only | _orch_hb_raw = self.redis.get("orchestrator:heartbeat_ms") if self.redis else None |
| 54039 | read_only | # No heartbeat key at all — orchestrator never started or Redis TTL expired |
| 54077 | read_only | f"GPU_STATS / util={gpu_util:.1f}% / vram={mem_stats.get('allocated_gb', 0):.2f}/{mem_stats.get('total_memory_gb', 16):.0f}GB / " |
| 54088 | read_only | """Convert Redis feature hash to numpy array for model input. |
| 54091 | read_only | features: decoded Redis feature hash (str keys preferred) |
| 54139 | read_only | key_order = self._per_sym_key_order_cache.get(_per_cache_key) |
| 54145 | read_only | if os.path.exists(_pin_path): |
| 54154 | write_metric | keys_set = set() |
| 54168 | read_only | vv = fdict.get(kk) |
| 54208 | write_signal | def _make_prediction(self, features: np.ndarray, symbol: str, timeframe: str, feature_dict: Dict[str, Any] = None, suppress_publish: bool = False): |
| 54217 | read_only | feature_dict: Original decoded feature dict from Redis (for trailing stop calculator) |
| 54218 | write_signal | suppress_publish: Pass through to _make_ppo_prediction for buffering support |
| 54221 | write_metric | When suppress_publish=True: dict or None |
| 54222 | write_metric | When suppress_publish=False: bool |
| 54241 | write_signal | result = self._make_ppo_prediction(features, symbol, timeframe, feature_dict=feature_dict, suppress_publish=suppress_publish) |
| 54250 | write_metric | return None if suppress_publish else False |
| 54296 | write_signal | def _make_ppo_prediction(self, features: np.ndarray, symbol: str, timeframe: str, feature_dict: Dict[str, Any] = None, suppress_publish: bool = False): |
| 54305 | read_only | feature_dict: Original decoded feature dict from Redis (for trailing stop calculator) |
| 54306 | write_signal | suppress_publish: If True, return signal payload dict instead of publishing (for buffering/deconfliction) |
| 54307 | write_metric | If False, publish immediately and return bool (legacy behavior) |
| 54310 | write_signal | When suppress_publish=True: dict (signal payload) or None (filtered out) |
| 54311 | write_metric | When suppress_publish=False: bool (True if published, False if filtered) |
| 54327 | write_metric | return None if suppress_publish else False |
| 54797 | read_only | required_confidence = min_confidence_by_tf.get(timeframe, 0.75) |
| 54800 | write_metric | # CRITICAL (Live): never require > MIN_CONF_ENTRY for publish gating. |
| 54804 | write_metric | # CRITICAL FIX B: Log every gating decision + publish intent |
| 54815 | write_metric | # SAFETY VALVE: Publish NaN to debug stream |
| 54821 | write_signal | self._signal_redis.xadd("signals:debug", {"data": json.dumps(nan_debug)}, maxlen=1000, approximate=True) |
| 54824 | write_metric | return None if suppress_publish else False |
| 54829 | write_signal | # PUBLISH_EVERYTHING debug toggle: bypass confidence filtering for end-to-end sanity testing |
| 54830 | write_metric | publish_everything = os.environ.get("PUBLISH_EVERYTHING", "0").lower() in ["1", "true", "yes"] |
| 54831 | write_metric | if publish_everything: |
| 54832 | write_signal | logger.info(f"🚨 [DEBUG] PUBLISH_EVERYTHING enabled - bypassing confidence filter for {symbol}:{timeframe} (conf={conf:.3f}, thr={thr:.3f})") |
| 54842 | read_only | min_close_conf = float(os.environ.get('MIN_CLOSE_CONFIDENCE', '0.55')) |
| 54848 | write_signal | self._signal_redis.hset(f"prediction:{symbol}:{timeframe}", mapping={ |
| 54850 | write_metric | "symbol": symbol, "timeframe": timeframe, "published": 0, "why": "low_conf_close", |
| 54852 | read_only | self._signal_redis.expire(f"prediction:{symbol}:{timeframe}", 1800) |
| 54855 | write_metric | return None if suppress_publish else False |
| 54858 | write_signal | # Only publish signals above dynamic confidence threshold (unless PUBLISH_EVERYTHING debug mode) |
| 54859 | write_metric | if not publish_everything and conf < thr: |
| 54861 | write_signal | # SAFETY VALVE: Publish filtered confidence to debug stream |
| 54867 | write_signal | self._signal_redis.xadd("signals:debug", {"data": json.dumps(conf_debug)}, maxlen=1000, approximate=True) |
| 54873 | write_signal | self._signal_redis.hset(f"prediction:{symbol}:{timeframe}", mapping={ |
| 54875 | write_metric | "symbol": symbol, "timeframe": timeframe, "published": 0, "why": f"low_conf_{conf:.3f}_vs_{thr:.3f}", |
| 54877 | read_only | self._signal_redis.expire(f"prediction:{symbol}:{timeframe}", 1800) |
| 54880 | write_metric | return None if suppress_publish else False |
| 54900 | read_only | redis_client = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 54902 | read_only | if redis_client is not None: |
| 54903 | read_only | feat_row = redis_client.hgetall(f"unified_features:{symbol}:{timeframe}") or {} |
| 54905 | read_only | feat_row = redis_client.hgetall(f"features:unified:{symbol}:{timeframe}") or {} |
| 54922 | read_only | scenario_adjusted_logit = float(blended_logit) + float(scenario_eval.get("logit_delta", 0.0)) |
| 54954 | read_only | _leg_rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 54969 | read_only | _leg_tf_votes = tf_agg.get("tf_votes", {}) |
| 54970 | read_only | _leg_bias = int(tf_agg.get("bias_dir", 0) or 0) |
| 54971 | read_only | _leg_timing = int(tf_agg.get("timing_dir", 0) or 0) |
| 55028 | read_only | _rc = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 55031 | read_only | _tr_feat = _rc.hgetall(f"unified_features:{symbol}:{_tr_tf}") |
| 55079 | read_only | _pos_side = str(current_pos.get("side", "") or "").upper() if current_pos else "" |
| 55151 | write_metric | return None if suppress_publish else False |
| 55154 | read_only | intrabar_state = self._fastlane_detector.get_intrabar_state(symbol, redis_client=self._signal_redis) |
| 55157 | write_metric | return None if suppress_publish else False |
| 55172 | write_metric | return None if suppress_publish else False |
| 55178 | read_only | redis_client=self._signal_redis, |
| 55183 | write_metric | return None if suppress_publish else False |
| 55188 | write_metric | return None if suppress_publish else False |
| 55193 | write_metric | return None if suppress_publish else False |
| 55204 | read_only | maxlen = getattr(self.main_config, "SIGNAL_STREAM_MAXLEN", 5000) |
| 55206 | write_signal | from utils.signal_publish import publish_trading_signal |
| 55208 | write_signal | publish_trading_signal( |
| 55209 | read_only | self._signal_redis, |
| 55212 | read_only | maxlen=maxlen, |
| 55217 | read_only | self._fastlane_detector.record_emit(symbol, fastlane_event, redis_client=self._signal_redis) |
| 55230 | read_only | "ts_ms": fastlane_event.get("ts_ms"), |
| 55231 | read_only | "event_id": fastlane_event.get("event_id"), |
| 55232 | read_only | "event_type": fastlane_event.get("event_type"), |
| 55233 | read_only | "severity": fastlane_event.get("severity"), |
| 55235 | read_only | "margin_usd": fastlane_payload.get("margin_usd", 0.0), |
| 55236 | read_only | "notional_usd": fastlane_payload.get("notional_usd", 0.0), |
| 55237 | read_only | "position_side": current_pos.get("side", "UNKNOWN"), |
| 55238 | read_only | "position_pnl_pct": current_pos.get("pnl_percentage", 0.0), |
| 55239 | read_only | "intrabar_snapshot": fastlane_event.get("intrabar_snapshot", {}), |
| 55242 | write_signal | self._signal_redis.xadd("signals:fastlane:debug", debug_record, maxlen=1000) |
| 55246 | write_checkpoint_metadata | return fastlane_payload if suppress_publish else True |
| 55248 | write_signal | logger.error(f"[FASTLANE] {symbol} - failed to publish signal: {e}") |
| 55249 | write_metric | return None if suppress_publish else False |
| 55264 | read_only | if exit_decision and exit_decision.get('action') in ( |
| 55270 | read_only | action_reason = exit_decision.get('reason', 'Exit/hedge decision') |
| 55284 | read_only | if float(tf_agg.get("conflict_score", 0.0) or 0.0) >= tf_conflict_block: |
| 55287 | read_only | f"conflict={float(tf_agg.get('conflict_score', 0.0)):.3f} >= {tf_conflict_block:.2f}" |
| 55291 | read_only | f"TF conflict gate: score {float(tf_agg.get('conflict_score', 0.0)):.3f} >= {tf_conflict_block:.2f}" |
| 55341 | read_only | current_position = position_decision.get('current_position') |
| 55359 | read_only | "margin_util": float((self._compute_risk_mode(symbol, final_action) or {}).get("margin_util", 0.0)) |
| 55378 | write_metric | from utils.ensemble_diagnostics import publish_ensemble_diagnostic |
| 55399 | read_only | chosen_action = int(action_to_int.get(str(final_action).upper(), 1)) |
| 55429 | read_only | _liq_rd_early = getattr(self, "redis", None) |
| 55431 | read_only | _liq_data_early = _liq_rd_early.hgetall(_liq_key_early) |
| 55433 | read_only | _liq_long_str_val = float(_liq_data_early.get("liquidation_long_strength", 0.0) or 0.0) |
| 55434 | read_only | _liq_short_str_val = float(_liq_data_early.get("liquidation_short_strength", 0.0) or 0.0) |
| 55438 | write_metric | publish_ensemble_diagnostic({ |
| 55448 | read_only | "scenario_logit_delta": float(scenario_eval.get("logit_delta", 0.0)), |
| 55449 | read_only | "scenario_top_action": str(scenario_eval.get("scenario_top_action", "HOLD")), |
| 55450 | read_only | "scenario_ev": float(scenario_eval.get("scenario_utility", 0.0)), |
| 55451 | read_only | "scenario_liq_prob": float(scenario_eval.get("scenario_liq_prob", 0.0)), |
| 55460 | read_only | "move_intensity": float(move_diag.get("move_intensity", 0.0)), |
| 55461 | read_only | "move_direction": str(move_diag.get("move_direction", "NEUTRAL")), |
| 55462 | read_only | "move_type": str(move_diag.get("move_type", "NORMAL")), |
| 55463 | read_only | "top_contributors": move_diag.get("top_contributors", []), |
| 55464 | read_only | "tf_bias_dir": int(tf_agg.get("bias_dir", 0) or 0), |
| 55465 | read_only | "tf_timing_dir": int(tf_agg.get("timing_dir", 0) or 0), |
| 55466 | read_only | "tf_conflict_score": float(tf_agg.get("conflict_score", 0.0) or 0.0), |
| 55467 | read_only | "tf_votes": tf_agg.get("tf_votes", {}), |
| 55490 | read_only | if isinstance(tf_summary, dict) and tf_summary.get("account_id"): |
| 55491 | read_only | acct_for_eq = str(tf_summary.get("account_id")).strip().lower() |
| 55497 | read_only | equity_for_limits = float(equity_snapshot.get("equity_usd", 0.0)) if equity_snapshot else 0.0 |
| 55498 | read_only | eq_ts = float(equity_snapshot.get("timestamp", 0.0) or 0.0) if equity_snapshot else 0.0 |
| 55502 | write_metric | # - Portfolio policy already enforces per-account equity staleness at publish time. |
| 55515 | write_metric | # Rely on per-account publish-time gating instead of blocking globally here. |
| 55544 | write_metric | # If portfolio policy is enabled and equity is stale, enforcement will happen at publish-time. |
| 55615 | write_metric | # CRITICAL FIX B: Log HOLD filtering (bypass with PUBLISH_EVERYTHING debug mode) |
| 55616 | write_signal | if not publish_everything and (final_action == "HOLD" or final_action == "NO_ACTION"): |
| 55619 | read_only | constraints = signal_payload.get("constraints_applied", []) or [] |
| 55708 | write_metric | # SAFETY VALVE: Publish HOLD to debug stream |
| 55715 | write_signal | self._signal_redis.xadd("signals:debug", {"data": json.dumps(hold_debug)}, maxlen=1000, approximate=True) |
| 55718 | write_metric | return None if suppress_publish else False |
| 55746 | read_only | _ah_redis = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 55747 | read_only | if _ah_redis: |
| 55748 | read_only | _ah_gate = AdaptiveGate(_ah_redis) |
| 55749 | read_only | _ah_side = str(current_position.get("side", "LONG")).upper() |
| 55750 | read_only | _ah_entry_px = float(current_position.get("entry_price", 0) or current_position.get("entryPrice", 0) or 0) |
| 55751 | read_only | _ah_mark_px = float(current_position.get("mark_price", 0) or current_position.get("markPrice", 0) or 0) |
| 55752 | read_only | _ah_pnl_pct = float(current_position.get("pnl_pct", 0) or current_position.get("unrealizedProfit", 0) or 0) |
| 55767 | read_only | if _ah_result.get("should_hold", False): |
| 55771 | read_only | f"ADX={_ah_result.get('adx', 0):.0f} RSI={_ah_result.get('rsi', 0):.0f} " |
| 55772 | read_only | f"ATR={_ah_result.get('atr_pct', 0):.4f}% / {_ah_result.get('reason', '')[:120]}" |
| 55790 | read_only | min_hold_minutes = float(os.environ.get("MIN_HOLD_MINUTES", "20")) |
| 55794 | read_only | current_position.get("entry_time") |
| 55795 | read_only | or current_position.get("timestamp") |
| 55796 | read_only | or current_position.get("opened_at") |
| 55800 | read_only | side_key = current_position.get("side", "LONG") if current_position else "LONG" |
| 55802 | read_only | raw_ts = self._signal_redis.hget(meta_key, "entry_time") if hasattr(self, "_signal_redis") else None |
| 55823 | read_only | if current_position and current_position.get('side'): |
| 55879 | read_only | close_side = current_position.get('side', 'LONG') if current_position else 'LONG' |
| 55887 | read_only | close_side = current_position.get('side', 'LONG') if current_position else 'LONG' |
| 55942 | read_only | mode_threshold = float(mode_confidence_thresholds.get(trade_mode, _min_entry)) |
| 55975 | read_only | equity_for_sizing = portfolio_state.get('total_balance') or portfolio_state.get('available_balance', 0.0) or 0.0 |
| 55982 | read_only | fb_eq = fb_state.get('total_balance') or fb_state.get('available_balance', 0.0) or 0.0 |
| 56068 | read_only | portfolio_state.get('available_balance', 0.0) |
| 56069 | read_only | or portfolio_state.get('available_margin', 0.0) |
| 56125 | read_only | "regime": market_state.get('market_regime', 'normal'), |
| 56127 | read_only | "overall_regime": regime_analysis.get('overall', 'normal'), |
| 56129 | read_only | "1m": regime_analysis.get('1m', 'normal'), |
| 56130 | read_only | "5m": regime_analysis.get('5m', 'normal'), |
| 56131 | read_only | "15m": regime_analysis.get('15m', 'normal'), |
| 56132 | read_only | "1h": regime_analysis.get('1h', 'normal'), |
| 56133 | read_only | "4h": regime_analysis.get('4h', 'normal'), |
| 56134 | read_only | "1d": regime_analysis.get('1d', 'normal') |
| 56138 | read_only | "volatility": market_state.get('volatility_5m', 0.5), |
| 56139 | read_only | "momentum": market_state.get('momentum_5m', 0.0), |
| 56140 | read_only | "stress_level": market_state.get('stress_level', 0.3), |
| 56141 | read_only | "volume_ratio": market_state.get('volume_ratio', 1.0), |
| 56142 | read_only | "funding_rate": market_state.get('funding_rate', 0.0), |
| 56143 | read_only | "is_high_volatility": market_state.get('is_high_volatility', False), |
| 56144 | read_only | "is_extreme_volatility": market_state.get('is_extreme_volatility', False), |
| 56153 | read_only | logger.info(f"   Overall Regime: {regime_analysis.get('overall', 'normal')} / Current TF: {regime_analysis.get(timeframe, 'normal')}") |
| 56154 | read_only | logger.info(f"   Multi-TF Regimes: 1m:{regime_analysis.get('1m', 'N')[:3]} 5m:{regime_analysis.get('5m', 'N')[:3]} 15m:{regime_analysis.get('15m', 'N')[:3]} 1h:{regime_analysis.get('1h', 'N')[:3]} 4h:{regime_analysis.get('4h', 'N')[:3]} 1d:{regime_analysis.get('1d', 'N')[:3]}") |
| 56155 | read_only | logger.info(f"   Volatility: {market_state.get('volatility_5m', 0.5):.3f} / Stress: {market_state.get('stress_level', 0.3):.3f} / Vol Ratio: {market_state.get('volume_ratio', 1.0):.2f}") |
| 56186 | read_only | account_id_for_signal = portfolio.get('active_account', self._resolve_target_account()) |
| 56202 | read_only | _liq_rd = getattr(self, "redis", None) |
| 56204 | read_only | _liq_data = _liq_rd.hgetall(_liq_key) |
| 56206 | read_only | _liq_long_str_val = float(_liq_data.get("liquidation_long_strength", 0.0) or 0.0) |
| 56207 | read_only | _liq_short_str_val = float(_liq_data.get("liquidation_short_strength", 0.0) or 0.0) |
| 56211 | read_only | # Read authoritative regime from Redis (compute_regime_from_redis cache) |
| 56214 | read_only | _auth_redis = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 56215 | read_only | if _auth_redis: |
| 56216 | read_only | _auth_raw = _auth_redis.get(f"regime:{symbol}") |
| 56256 | read_only | "scenario_logit_delta": float(scenario_eval.get("logit_delta", 0.0)), |
| 56257 | read_only | "scenario_top_action": str(scenario_eval.get("scenario_top_action", "HOLD")), |
| 56258 | read_only | "scenario_ev": float(scenario_eval.get("scenario_utility", 0.0)), |
| 56259 | read_only | "scenario_liq_prob": float(scenario_eval.get("scenario_liq_prob", 0.0)), |
| 56260 | read_only | "move_intensity": float(move_diag.get("move_intensity", 0.0)), |
| 56261 | read_only | "move_direction": str(move_diag.get("move_direction", "NEUTRAL")), |
| 56262 | read_only | "move_type": str(move_diag.get("move_type", "NORMAL")), |
| 56263 | read_only | "move_top_contributors": move_diag.get("top_contributors", []), |
| 56272 | read_only | "tf_votes": tf_agg.get("tf_votes", {}), |
| 56273 | read_only | "tf_bias_dir": int(tf_agg.get("bias_dir", 0) or 0), |
| 56274 | read_only | "tf_timing_dir": int(tf_agg.get("timing_dir", 0) or 0), |
| 56275 | read_only | "tf_conflict_score": float(tf_agg.get("conflict_score", 0.0) or 0.0), |
| 56291 | read_only | "regime_direction": (market_regime_info or {}).get("regime_direction") if isinstance(market_regime_info, dict) else None, |
| 56292 | read_only | "regime_stress": (market_regime_info or {}).get("regime_stress") if isinstance(market_regime_info, dict) else None, |
| 56293 | read_only | "regime_structure": (market_regime_info or {}).get("regime_structure") if isinstance(market_regime_info, dict) else None, |
| 56294 | read_only | "structural_risk_mode": (market_regime_info or {}).get("risk_mode") if isinstance(market_regime_info, dict) else None, |
| 56295 | read_only | # Authoritative regime from compute_regime_from_redis (single source of truth) |
| 56296 | read_only | "move_regime": _auth_regime.get("move_regime", "UNKNOWN"), |
| 56297 | read_only | "trend_direction": _auth_regime.get("trend_direction", "NEUTRAL"), |
| 56298 | read_only | "tf_alignment": float(_auth_regime.get("tf_alignment", 0.0) or 0.0), |
| 56299 | read_only | "volatility_score": float(_auth_regime.get("volatility_score", 0.0) or 0.0), |
| 56300 | read_only | "liq_risk": float(_auth_regime.get("liq_risk", 0.0) or 0.0), |
| 56301 | read_only | "liquidity_score": float(_auth_regime.get("liquidity_score", 0.0) or 0.0), |
| 56310 | read_only | "portfolio_balance": float(portfolio_state.get('total_balance', equity_for_sizing) or equity_for_sizing or 0.0), |
| 56314 | read_only | "close_fraction": float(position_decision.get('close_fraction', 1.0)),  # Default 1.0 = full close |
| 56315 | read_only | "hedge_fraction": float(position_decision.get('hedge_fraction', 0.0)),  # Default 0.0 = no hedge |
| 56316 | read_only | "rebalance_mode": position_decision.get('source', None),  # 'dynamic_monitor', 'time_in_loss_hedge', etc. |
| 56319 | read_only | "margin_utilization": float(portfolio_state.get('margin_utilization_pct', 0.0) or 0.0), |
| 56320 | read_only | "used_margin": float(portfolio_state.get('total_margin_used', 0.0) or 0.0), |
| 56322 | read_only | portfolio_state.get('total_margin_balance', 0.0) |
| 56323 | read_only | or portfolio_state.get('total_balance', 0.0) |
| 56391 | read_only | _sig_category = signal_payload.get("action_category", "OPEN_RISK") |
| 56397 | read_only | _vhtf_bias = signal_payload.get("vhtf_bias", 0) |
| 56418 | write_metric | # TRAINER INTENT PUBLISHER (Feb 2026 — Post-Liquidation Fix) |
| 56420 | write_metric | # Publish the trainer's directional conviction to Redis so that |
| 56426 | write_signal | from risk.trainer_intent import publish_intent, infer_direction_from_action |
| 56428 | read_only | _intent_redis = getattr(self, "_signal_redis", None) or getattr(self, "redis", None) |
| 56429 | read_only | if _intent_redis is not None: |
| 56430 | write_metric | publish_intent( |
| 56431 | read_only | redis_client=_intent_redis, |
| 56440 | write_metric | logger.debug(f"[TRAINER_INTENT] publish failed for {symbol}: {_intent_err}") |
| 56446 | write_metric | # The "direct xadd" predictor path (this function) previously skipped that cache entirely, |
| 56449 | read_only | # Contract (see AUDIT_REDIS_IO_KEYS.md): Redis hash with 120s TTL. |
| 56458 | read_only | if ENABLE_PRICE_TARGET_PREDICTION and signal_payload.get("price_target") is None: |
| 56492 | read_only | atr_pct = float(signal_payload.get("atr_pct") or 0.0) |
| 56497 | read_only | atr_abs = float(feature_dict.get("atr_14") or 0.0) |
| 56502 | read_only | _rc_d = getattr(self, '_signal_redis', None) or getattr(self, 'redis', None) |
| 56507 | read_only | _pt = _compute_price_target( |
| 56518 | read_only | "action": str(signal_payload.get("action_name") or action_name or "").upper(), |
| 56519 | read_only | "confidence": str(float(signal_payload.get("model_confidence", signal_payload.get("confidence", 0.0)) or 0.0)), |
| 56520 | read_only | "ppo_confidence": str(float(signal_payload.get("ppo_confidence", 0.0) or 0.0)), |
| 56521 | read_only | "masa_confidence": str(float(signal_payload.get("masa_confidence", 0.0) or 0.0)), |
| 56522 | read_only | "blended_logit": str(float(signal_payload.get("blended_logit", 0.0) or 0.0)), |
| 56526 | write_metric | "published": 0, |
| 56529 | read_only | if signal_payload.get("price_target") is not None: |
| 56530 | read_only | pred_map["price_target"] = str(signal_payload.get("price_target")) |
| 56531 | read_only | if signal_payload.get("price_target_pct") is not None: |
| 56532 | read_only | pred_map["price_target_pct"] = str(signal_payload.get("price_target_pct")) |
| 56533 | read_only | if signal_payload.get("price_target_direction") is not None: |
| 56534 | read_only | pred_map["price_target_direction"] = str(signal_payload.get("price_target_direction")) |
| 56538 | write_signal | self._signal_redis.hset(pred_key, mapping=pred_map) |
| 56539 | read_only | self._signal_redis.expire(pred_key, 1800)  # 30 min TTL (was 120s - caused deadlock) |
| 56548 | read_only | constraints = list(signal_payload.get("constraints_applied", [])) |
| 56550 | write_metric | if not filter_result['should_generate'] and not suppress_publish: |
| 56556 | read_only | if signal_payload.get("cooldown_active"): |
| 56577 | write_metric | return None if suppress_publish else False |
| 56592 | read_only | self._signal_redis.setex(conf_key, 300, str(conf))  # 5 min TTL |
| 56597 | write_signal | # This must happen for ALL signals, not just during publish, so the full |
| 56607 | write_signal | # Publish signal to Redis stream OR return payload for buffering |
| 56608 | write_metric | if suppress_publish: |
| 56611 | read_only | _buf_conf = float(signal_payload.get('model_confidence', conf) or conf) |
| 56615 | write_metric | # CRITICAL FIX B: Log actual publishing + fail loudly on errors |
| 56618 | read_only | if signal_payload.get("cooldown_active"): |
| 56624 | write_metric | # ROOT FIX: PER-ACCOUNT SIZING AND PUBLISHING |
| 56626 | write_metric | # Now: For each account, calculate sizing using THAT account's equity, publish to its stream only |
| 56631 | write_metric | # Per-account mode: iterate accounts, recalculate sizing per-account, publish to each stream |
| 56632 | read_only | maxlen = getattr(self.main_config, "SIGNAL_STREAM_MAXLEN", 5000) |
| 56636 | read_only | target_stream = SIGNAL_STREAM_PER_ACCOUNT.get(account_id) |
| 56643 | read_only | acct_equity = acct_portfolio_state.get('total_balance') or acct_portfolio_state.get('available_balance', 0.0) or 0.0 |
| 56663 | read_only | acct_available_margin = float(acct_portfolio_state.get('available_balance', 0.0) or acct_portfolio_state.get('available_margin', 0.0) or 0.0) |
| 56684 | write_metric | # Publish to THIS account's stream only |
| 56686 | write_risk_state | # ── FORBIDDEN_DIRECT_PUBLISH guard ────────────────────────────── |
| 56687 | write_metric | # In orchestrator publish-mode this path is structural dead code. |
| 56689 | write_metric | if str(os.getenv("ORCHESTRATOR_WORKER_MODE", "")).lower() == "publish": |
| 56691 | write_metric | "FORBIDDEN_DIRECT_PUBLISH_IN_ORCH_PUBLISH_MODE: " |
| 56692 | write_metric | f"per-account stream publish attempted for {account_id}:{symbol}. " |
| 56695 | write_signal | from utils.signal_publish import publish_trading_signal |
| 56696 | write_metric | from utils.ensemble_diagnostics import publish_ensemble_diagnostic |
| 56698 | write_metric | # Decision-level proof event on active publish path. |
| 56699 | read_only | decision_id = acct_signal_payload.get("decision_id") or f"{int(time.time()*1000)}-{symbol}-{timeframe}-{account_id}" |
| 56701 | write_metric | publish_ensemble_diagnostic({ |
| 56710 | read_only | "move_intensity": float((move_diag or {}).get("move_intensity", 0.0)) if "move_diag" in locals() else 0.0, |
| 56711 | read_only | "move_direction": str((move_diag or {}).get("move_direction", "NEUTRAL")) if "move_diag" in locals() else "NEUTRAL", |
| 56712 | read_only | "move_type": str((move_diag or {}).get("move_type", "NORMAL")) if "move_diag" in locals() else "NORMAL", |
| 56713 | read_only | "scenario_top_action": str((scenario_eval or {}).get("scenario_top_action", "HOLD")) if "scenario_eval" in locals() else "HOLD", |
| 56714 | read_only | "scenario_ev": float((scenario_eval or {}).get("scenario_utility", 0.0)) if "scenario_eval" in locals() else 0.0, |
| 56715 | read_only | "scenario_liq_prob": float((scenario_eval or {}).get("scenario_liq_prob", 0.0)) if "scenario_eval" in locals() else 0.0, |
| 56716 | read_only | "logit_delta": float((scenario_eval or {}).get("logit_delta", 0.0)) if "scenario_eval" in locals() else 0.0, |
| 56722 | write_signal | stream_id = publish_trading_signal( |
| 56723 | read_only | self._signal_redis, |
| 56726 | read_only | maxlen=maxlen, |
| 56730 | write_signal | logger.info(f"✅ [PER_ACCOUNT_PUBLISH] {account_id} → {target_stream} / {symbol}:{timeframe} {action_name} margin=${acct_margin_usd:.2f}") |
| 56732 | write_metric | logger.error(f"🚨 [PER_ACCOUNT_PUBLISH] Failed for {account_id}: {pub_err}") |
| 56735 | write_risk_state | # ── FORBIDDEN_DIRECT_PUBLISH guard ────────────────────────────── |
| 56736 | write_metric | if str(os.getenv("ORCHESTRATOR_WORKER_MODE", "")).lower() == "publish": |
| 56738 | write_metric | "FORBIDDEN_DIRECT_PUBLISH_IN_ORCH_PUBLISH_MODE: " |
| 56739 | write_metric | f"legacy single-stream publish attempted for {symbol}:{timeframe}. " |
| 56743 | write_signal | logger.info(f"🚀 [PREDICT] Publishing: {symbol}:{timeframe} action={action_name} conf={conf:.3f} streams={target_streams}") |
| 56745 | read_only | maxlen = getattr(self.main_config, "SIGNAL_STREAM_MAXLEN", 5000) |
| 56750 | write_signal | from utils.signal_publish import publish_trading_signal |
| 56751 | write_signal | stream_id = publish_trading_signal( |
| 56752 | read_only | self._signal_redis, |
| 56755 | read_only | maxlen=maxlen, |
| 56760 | write_signal | # Common post-publish actions for both paths |
| 56761 | write_signal | logger.info(f"✅ [PREDICT] Published → {len(stream_ids)} stream(s) / {symbol}:{timeframe} {action_name} conf={conf:.3f}") |
| 56763 | write_signal | # Mark prediction cache as published=1 (best-effort; don't fail publish on cache issues) |
| 56766 | write_signal | self._signal_redis.hset(pred_key, mapping={"published": 1, "timestamp": str(time.time())}) |
| 56767 | read_only | self._signal_redis.expire(pred_key, 1800)  # 30 min TTL (was 120s) |
| 56771 | write_metric | # SAFETY VALVE: Always publish to debug stream (no filtering) |
| 56773 | write_checkpoint_metadata | debug_payload['debug_published_at'] = time.time() |
| 56774 | write_checkpoint_metadata | debug_payload['debug_reason'] = f"published_conf_{conf:.3f}_thr_{thr:.3f}" |
| 56776 | write_signal | self._signal_redis.xadd( |
| 56779 | read_only | maxlen=1000, |
| 56782 | write_signal | logger.debug(f"🔍 [DEBUG] Safety valve published → signals:debug") |
| 56784 | write_signal | logger.debug(f"[DEBUG] Failed to publish debug signal: {debug_err}") |
| 56795 | read_only | if self._signal_redis is not None: |
| 56797 | write_signal | self._signal_redis.hset( |
| 56801 | write_metric | except Exception as hset_err: |
| 56802 | write_signal | logger.debug(f"[SIGNAL] Failed to update last prediction hash: {hset_err}") |
| 56805 | write_signal | logger.debug(f"[SIGNAL] {symbol}:{timeframe} PUBLISHED - PPO: {ppo_logit:.3f}, MASA: {masa_logit:.3f}, Confidence: {confidence:.3f}, Threshold: {required_confidence:.3f}") |
| 56811 | write_metric | return None if suppress_publish else False |
| 56825 | read_only | # Get feature data from Redis |
| 56827 | read_only | features = self._signal_redis.hgetall(feature_key) |
| 56833 | read_only | ts_ms = int(features.get('ts_ms', 0)) |
| 56859 | read_only | 'current_position': position_decision.get('current_position'), |
| 56869 | write_signal | # Publish signal to Redis stream (if Redis available) |
| 56870 | read_only | if self._signal_redis is not None: |
| 56872 | write_signal | from utils.signal_publish import publish_trading_signal |
| 56873 | write_signal | publish_trading_signal( |
| 56874 | read_only | self._signal_redis, |
| 56877 | read_only | maxlen=5000, |
| 56882 | write_signal | self._signal_redis.hset( |
| 56886 | read_only | except Exception as redis_err: |
| 56887 | write_metric | logger.warning(f"[RULE_BASED] Redis publish failed: {redis_err}") |
| 56889 | write_metric | logger.debug(f"[RULE_BASED] Skipped Redis publish - no connection") |
| 56973 | read_only | for balance in account_info.get('balances', []): |
| 56974 | read_only | asset = balance.get('asset', '') |
| 56975 | read_only | free = float(balance.get('free', 0)) |
| 56976 | read_only | locked = float(balance.get('locked', 0)) |
| 56996 | read_only | margin_ratio = float(futures_account.get('totalMarginBalance', 0)) / float(futures_account.get('totalWalletBalance', 1)) if futures_account.get('totalWalletBalance', 0) > 0 else 0 |
| 56998 | read_only | for position in futures_account.get('positions', []): |
| 56999 | read_only | unrealized_pnl += float(position.get('unrealizedProfit', 0)) |
| 57038 | read_only | reason_code = str(feedback.get('reason_code') or '').upper() |
| 57039 | read_only | account_id = str(feedback.get('account_id') or 'primary') |
| 57040 | read_only | symbol = feedback.get('symbol') |
| 57041 | read_only | action = feedback.get('action') |
