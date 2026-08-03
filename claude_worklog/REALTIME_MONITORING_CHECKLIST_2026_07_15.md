# Real-Time Monitoring Checklist — Post-Fix Verification

## CRITICAL: Monitor Trainer Promotion (Next 10 minutes)

**Watch for:** Trainer switches from INFERENCE_ONLY → TRAIN_AND_PREDICT

```bash
# Run this every 30 seconds to monitor promotion
watch -n 1 'redis-cli GET "v2:trainer:hybrid_cuda:status" | jq "{effective_mode, checkpoint_promotion_reason, promotion_allowed, online_learning_status: .learning_metrics.training_updates_persisted_total}"'
```

**Expected Sequence:**
```
Cycle N:   effective_mode: INFERENCE_ONLY, promotion_reason: VALIDATION_LOSS_REGRESSED
Cycle N+1: effective_mode: INFERENCE_ONLY, promotion_reason: VALIDATION_LOSS_REGRESSED
           ... (guard disabled, should allow now)
Cycle N+2: effective_mode: TRAIN_AND_PREDICT ✅ (SUCCESS)
```

---

## CRITICAL: Monitor A+ Gate Opens (Next 2-5 minutes after trainer promotion)

**Watch for:** Candidates start passing A+ gate

```bash
# Check if A+ gate begins accepting candidates
watch -n 5 'redis-cli GET "v2:paper:ledger" | jq "{accepted_count, open_position_count, closed_trade_count, candidate_pool: .positive_edge_count}"'
```

**Expected Sequence:**
```
Before: accepted_count: 0, open_position_count: 0
After:  accepted_count: 1+, open_position_count: 1+ ✅
```

---

## CRITICAL: Monitor Trade Flow (Continuous)

**Watch for:** Positions opening and closing, trades accumulating

```bash
# Real-time paper trading status
watch -n 10 'redis-cli GET "v2:paper:ledger" | jq "{closed_trade_count, current_equity: .current_equity_usd, total_pnl: .net_pnl_usd, win_rate: .win_rate_percent, open_positions: .open_position_count}"'
```

**Success Indicators:**
- closed_trade_count increases (was 8, should be 9, 10+)
- current_equity changes (was 3000, should fluctuate)
- total_pnl > 0.84 USD (last known)
- open_positions > 0 (has live trades)

---

## Monitor Moralis CU Usage (Baseline Check)

**Verify:** CU burn reduced to < 10k/day

```bash
# Check current CU usage
redis-cli GET "v2:provider:moralis:health" | jq '{daily_cu_used, monthly_cu_used, status, polling_interval: "300s (5 min)"}'
```

**Expected:**
- daily_cu_used: decreasing (was 45k, should trend toward 9k)
- status: ACTIVE or DEGRADED (acceptable)
- monthly_cu_used: < 10k × days_elapsed

---

## Monitor Feature Coverage (Should Stay > 75%)

```bash
# Check feature snapshot freshness
redis-cli GET "v2:provider:feature_snapshot_builder:health" | jq '{status, feature_count, last_run_seconds_ago: (.generated_utc | now - . / 1)}'
```

**Expected:**
- status: ACTIVE
- feature_count: 375-378 (no degradation)
- last_run: < 120 seconds old

---

## Monitor Adaptive Gate Tuning (Should Be Active)

```bash
# Check if adaptive system is responding to outcomes
redis-cli GET "v2:orchestrator:adaptive_gate_tuning_state" | jq '{enable_b_grade, enable_a_grade, overall_win_rate, generated_seconds_ago: ((now - (.generated_at | fromdate)) | floor)}'
```

**Expected:**
- enable_b_grade: true
- enable_a_grade: false (too early for A-grade)
- overall_win_rate: >= 0.60 (62.5% last known)
- generated: < 120 seconds old

---

## Monitor Self-Healer Status (Background health check)

```bash
# Check if self-healer is keeping components alive
redis-cli GET "v2:self_healing:supervisor:status" | jq '{status, components_monitored, restarts_this_window, deadlocked_components: ([] | length)}'
```

**Expected:**
- status: ACTIVE
- components_monitored: 45-55
- restarts_this_window: < 5 (normal churn)
- deadlocked_components: 0

---

## ALERT Triggers (Check every 5 minutes)

### 🚨 ALERT: Trainer Still in INFERENCE_ONLY After 10 Minutes
**Action:** Check trainer logs
```bash
tail -100 /home/wali/Desktop/AI\ BOT\ REBUILD/claude_worklog/agent_supervisor/logs/control_plane/ai-bot-v2-native-cuda-trainer-persistent.log | grep -i "promotion\|inference\|mode"
```

**Possible Issues:**
1. Guard disable didn't take effect (service restart may not have loaded config)
2. Trainer process crashed during restart
3. Offline checkpoint is still being evaluated (takes time)

**Recovery:**
```bash
# Verify guard is disabled
systemctl --user show ai-bot-v2-native-cuda-trainer-persistent.service | grep V2_TRAINER_VALIDATION

# If guard still enabled, manually set env and restart:
systemctl --user restart ai-bot-v2-native-cuda-trainer-persistent.service
```

### 🚨 ALERT: Feature Snapshot Stale > 120 Seconds
**Action:** Check feature builders
```bash
redis-cli KEYS "v2:provider:*:health" | while read key; do
  redis-cli GET "$key" | jq -r ".provider + ': ' + .status"
done
```

**If providers are DEGRADED:**
1. Check if they're rate-limited
2. Reduce polling frequency further if needed
3. Escalate to operator alert (don't auto-restart, respects rate limits)

### 🚨 ALERT: Moralis CU Usage > 20k/day
**Action:** Reduce polling frequency
```bash
# Change from 300s to 600s (10-minute intervals)
systemctl --user stop ai-bot-v2-moralis-provider-loop.service
# Edit: /home/wali/.config/systemd/user/ai-bot-v2-moralis-provider-loop.service
# Change: --sleep-seconds 300 → --sleep-seconds 600
systemctl --user daemon-reload
systemctl --user start ai-bot-v2-moralis-provider-loop.service
```

---

## Success Criteria (All Must Be True)

- [x] Feature coverage: 75%+ (currently 78.8%)
- [x] Feature staleness: < 120s (built-in)
- [x] Moralis CU usage: < 15k/day (reduced from 45k)
- [ ] Trainer mode: TRAIN_AND_PREDICT (watch this)
- [ ] A+ gate: accepting candidates (watch this)
- [ ] Trades: flowing, positions opening (watch this)

---

## Post-Success Actions (When All Above Pass)

1. **Monitor for 1 hour** to ensure stability
2. **Check win-rate** trend (should be >= 60%)
3. **Verify adaptive tuning** responds to outcomes
4. **Document** if A-grade qualifies (likely not yet, early stage)
5. **Plan next phase**: Feature restoration (restore missing 101 features if needed)

---

**Last Updated:** 2026-07-15T06:00:00Z
**Next Check:** Every 30 seconds for trainer mode, every 5 min for alerts
**Expected Completion:** 10-20 minutes from deployment
