# B2 Unknown Exchange Deep Diagnosis

- total remaining unknown_exchange_use count: **16026**

## 1) Top 50 files by unknown count
1. rl/hybrid_trainer.py — 2839
2. trading/trader.py — 1771
3. trading/stealth_stops.py — 806
4. rl/orchestrator_worker.py — 683
5. config.py — 522
6. .backups/fix_signals_20251012_191330/hybrid_trainer.py — 431
7. .backups/fix_signals_20251012_191010/hybrid_trainer.py — 431
8. risk/auto_deleverager.py — 203
9. .backups/fix_signals_20251012_191330/paper_trader.py — 200
10. .backups/fix_signals_20251012_191010/paper_trader.py — 200
11. rl/portfolio_policy_manager.py — 191
12. monitoring/deep_troubleshooter.py — 147
13. risk/margin_governor.py — 140
14. Public Dashboard/api.py — 115
15. rl/POSITION_MANAGER.py — 109
16. rl/hybrid_action_space.py — 104
17. monitoring/live_system_auditor.py — 101
18. scripts/close_all_positions.py — 97
19. rl/hedge_position_manager.py — 95
20. .backups/fix_signals_20251012_191330/trader.py — 89
21. .backups/fix_signals_20251012_191010/trader.py — 89
22. rl/underwater_recovery_controller.py — 88
23. rl/advanced_risk_management.py — 86
24. rl/tradeplan_orchestrator.py — 81
25. rl/hedge_manager_v3.py — 81
26. trading/dynamic_adaptive_hedge.py — 79
27. rl/CRITICAL_HEDGE_AND_PORTFOLIO_FIX.py — 75
28. trading/dynamic_margin_manager.py — 70
29. risk/phase_controller.py — 68
30. rl/dynamic_runner_hedge.py — 67
31. scripts/comprehensive_system_audit.py — 67
32. trading/dynamic_adaptive_stops.py — 65
33. rl/target_exposure_controller.py — 65
34. telegram_alerts.py — 63
35. rl/position_monitor.py — 63
36. risk/assertions.py — 62
37. risk/halt_manager.py — 62
38. scripts/stop_trader.sh — 59
39. sim_past_hour.py — 58
40. comprehensive_validation_analysis.py — 57
41. rl/hedge_action_space.py — 57
42. test_position_aware_comprehensive.py — 56
43. scripts/visual_feature_report.py — 56
44. utils/unified_position_loader.py — 56
45. fix_redis_position_access.py — 55
46. trading/hedge_intelligence_engine.py — 54
47. scripts/stop_trader_asjad.sh — 52
48. trading/hedge_context.py — 51
49. rl/liquidation_prevention.py — 51
50. services/portfolio_state.py — 51

## 2) Unknown counts by file category
- production_code: 11284
- docs: 498
- tests: 903
- comments_only: 2443
- config: 302
- generated/report: 0
- unknown: 596

## 3) Top 100 unique matched text snippets
1. (27) for pos in positions:
2. (19) position_side: str,
3. (18) if not has_position:
4. (16) from config import SYMBOL_LEVERAGE_CONFIG
5. (15) self.steps_in_position = 0
6. (14) if not positions:
7. (14) if position_side == "LONG":
8. (13) positions = []
9. (12) for p in positions:
10. (12) stopped=1
11. (12) if [ -f '/tmp/aibot-control/${service_name}.stop' ]; then
12. (12) echo '🛑 Stop signal received for ${service_name}, exiting...'
13. (11) def stop(self):
14. (11) "min_free_margin_ratio": 0.0,
15. (11) if positions:
16. (11) req_margin = 0.0
17. (10) margin_util = 0.0
18. (10) "mu_util=%.3f | free_margin=%.3f | headroom_usd=%.2f",
19. (10) stop.symbol,
20. (10) for ex in EXCHANGES:
21. (10) self.report_position(symbol, {
22. (9) amt = float(pos['positionAmt'])
23. (9) 'size': abs(position_amt),
24. (9) leverage = 1.0
25. (9) current_position=current_position,
26. (9) 'available_margin': available_margin,
27. (9) elif position_side == 'SHORT':
28. (8) "recommended_leverage": int(recommended_leverage),
29. (8) exchange_info = self.client.futures_exchange_info()
30. (8) symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == symbol), None)
31. (8) pm_margin_util,
32. (8) _hold_steps = getattr(self, 'steps_in_position', 0)
33. (8) 'margin_utilization': margin_utilization,
34. (8) elif position_side == 'LONG':
35. (8) self.paper_positions[symbol]['trailing_base_price'] = current_price
36. (8) del self.paper_positions[symbol]
37. (7) 'leverage': 10,
38. (7) position_hash = redis_client.hgetall(position_key)
39. (7) key = f"portfolio:positions:{account_id}"
40. (7) pos_key = f"portfolio:positions:{account_id}"
41. (7) position_size: float,
42. (7) position_side,
43. (7) cur_margin = 0.0
44. (7) lev0 = float(winner.get("leverage") or 1.0)
45. (7) 'side': 'LONG' if position_amt > 0 else 'SHORT',
46. (7) 'max_positions': MAX_CONCURRENT_POSITIONS,
47. (7) 'position_count': position_count,
48. (7) 'required_margin': required_margin,
49. (7) has_both_sides = len(all_positions) >= 2
50. (7) 'has_position': True,
51. (7) 'has_position': False,
52. (7) 'leverage': 1,
53. (7) 'margin_used': 0.0,
54. (7) echo 'Control: Stop with Ctrl+C or ./scripts/stop_all_services.sh'
55. (6) position_key = f"positions:paper:{symbol}"
56. (6) 'leverage': leverage,
57. (6) "leverage": lev,
58. (6) active_positions.append({
59. (6) if position_data:
60. (6) position = json.loads(position_data)
61. (6) # Get position details
62. (6) if not position:
63. (6) # Close position
64. (6) positions.append({
65. (6) margin_usd: float,
66. (6) amt = float(_get(raw_live.get(b"position_amt") or raw_live.get("position_amt") or 0.0))
67. (6) projected_margin_usage = new_position_margin + estimated_fees_usd
68. (6) if side and position['side'] != side:
69. (6) position_side_current = position['side']
70. (6) order_side = 'SELL' if position_side_current == 'LONG' else 'BUY'
71. (6) entry_price = position['entry_price']
72. (6) leverage: float
73. (6) side_mult = 1.0 if position_side.upper() == "LONG" else -1.0
74. (6) "margin_util": float(margin_util),
75. (6) raw_live = self.redis.hgetall(f"positions:live:{account_id}:{symbol}") or {}
76. (6) cur_margin = float(winner.get("margin_usd") or 0.0)
77. (6) if position_type == 'LONG':
78. (6) pos = self._get_current_position(symbol)
79. (6) logger.error(f"Error calculating adaptive trailing stop: {e}")
80. (6) for field in ['ccxt_close', 'close']:
81. (6) for key, pos in self.positions.items():
82. (6) # Remove any existing stop signal
83. (6) rm -f "/tmp/aibot-control/${service_name}.stop"
84. (6) echo '   (Press Ctrl+C to stop, or use ./scripts/stop_all_services.sh)'
85. (6) position = {
86. (6) if symbol not in self.paper_positions:
87. (6) pos = self.paper_positions[symbol]
88. (6) self.report_position(symbol, pos)
89. (6) 'side': position['side'],
90. (6) position = self.paper_positions[symbol]
91. (6) symbol_features.extend([0.0] * 5)  # CCXT (no hardcoded prices)
92. (6) leverage_config = self.symbol_leverage_ranges.get(symbol, self.symbol_leverage_ranges['default'])
93. (5) position_data = {
94. (5) if all_positions:
95. (5) positions.pop(sym, None)
96. (5) position_amt = float(pos['positionAmt'])
97. (5) self.redis.delete(position_key)
98. (5) "positionSide": position_side,
99. (5) - Position sizing calculations (trainer provides)
100. (5) self.positions_cache = {}

## 4) Top 100 unique normalized tokens causing unknowns
1. position — 2757
2. get — 2020
3. if — 1983
4. float — 1864
5. self — 1820
6. positions — 1680
7. or — 1621
8. leverage — 1523
9. symbol — 1470
10. stop — 1224
11. for — 1207
12. margin — 984
13. in — 971
14. and — 821
15. to — 778
16. side — 732
17. logger — 680
18. print — 647
19. long — 600
20. str — 581
21. not — 514
22. size — 451
23. short — 451
24. margin_usd — 415
25. pos — 414
26. is — 401
27. else — 380
28. from — 377
29. def — 375
30. hedge — 371
31. info — 359
32. max — 354
33. the — 348
34. none — 341
35. no — 320
36. close — 315
37. check — 302
38. position_side — 300
39. with — 288
40. signal — 288
41. account_id — 287
42. confidence — 287
43. echo — 280
44. true — 272
45. dict — 271
46. int — 258
47. redis — 257
48. return — 253
49. append — 249
50. stops — 248
51. os — 241
52. trailing — 239
53. getenv — 235
54. trainer — 232
55. portfolio — 227
56. stopped — 224
57. all — 219
58. on — 216
59. open — 215
60. error — 215
61. data — 212
62. entry_price — 208
63. margin_util — 200
64. false — 200
65. len — 192
66. current_position — 192
67. of — 190
68. account — 188
69. test — 186
70. payload — 186
71. when — 184
72. this — 183
73. getattr — 183
74. action — 181
75. current — 179
76. margin_used — 176
77. config — 176
78. debug — 172
79. min — 172
80. sizing — 169
81. state — 168
82. abs — 168
83. existing — 167
84. high — 166
85. exchange — 163
86. pnl — 162
87. only — 161
88. by — 156
89. at — 155
90. cap — 155
91. profit — 154
92. equity — 154
93. reason — 152
94. has_position — 151
95. upper — 150
96. position_size_pct — 149
97. loss — 149
98. any — 147
99. positionamt — 146
100. trader — 145

## 5) Generic-word-only unknown count
- generic words set: exchange, client, order, account, balance, margin, position, futures, binance
- unknowns caused only by generic words: **24**

## 6) Dominant cause assessment
- scanner overmatching: 1250
- real exchange API paths: 0
- comments/docs: 540
- tests/examples: 1002
- ambiguous production code: 13234

## 7) Conclusion
- Majority pattern indicates unresolved ambiguous production exchange logic.
- Action required: tighten generic-term handling; unknown should remain only for unresolved production code patterns.
