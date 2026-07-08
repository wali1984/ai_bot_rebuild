# Current Gaps and Blockers — AI BOT V2
Generated: 2026-07-01
Audit: V2_REBUILD_MASTER_END_TO_END_SYSTEM_AUDIT_AND_OPERATOR_MANUAL

---

## Gap Classification Summary

| Priority | Count | Status |
|----------|-------|--------|
| P0 — Critical blocker | 2 | OPEN |
| P1 — High severity | 3 | OPEN |
| P2 — Medium severity | 3 | OPEN |
| P3 — Low severity | 3 | OPEN |
| **Total** | **11** | |

---

## P0 — Critical Blockers (Must resolve before any progress review)

### GAP_P0_001: Trainer Feedback Loop 100% Quarantined

**Description**: 741 of 741 paper trade outcome feedback rows are quarantined. 0 rows are consumable. The trainer is not receiving any reward signal from paper trade outcomes, meaning it cannot learn from paper trade results.

**Impact**: Trainer improvement is frozen. The PPO training loop is running but operating without outcome feedback, which means it is training on features only (without reward signal from trade outcomes). Model quality cannot improve from paper results.

**Evidence**:
- `v2:paper:ledger` → `trainer_feedback_consumable_row_count: 0`
- `v2:paper:ledger` → `trainer_feedback_quarantined_row_count: 741`
- Redis key `v2:trainer:feedback:outcomes` exists but all rows have quarantine flag set

**Root cause**: Unknown — requires investigation of quarantine reason codes in `v2:trainer:feedback:outcomes`. Likely cause: pipeline trust enforcement epoch mismatch (`enforcement_epoch: pipeline_trust_v3_20260612`) caused all feedback rows generated before or during the trust epoch change to be quarantined.

**Resolution path**:
1. Read `v2:trainer:feedback:outcomes` and examine quarantine_reason field
2. If quarantine_reason = "TRUST_EPOCH_MISMATCH": run `v2_paper_outcome_memory_rebuild.py` to rebuild with current trust epoch
3. Verify consumable count increases: `redis-cli get v2:paper:ledger | python3 -c "import sys,json; d=json.load(sys.stdin); print('consumable:', d.get('trainer_feedback_consumable_row_count',0))"`
4. If quarantine_reason = other: investigate paper shadow outcome observer for quarantine decision logic

**Resolution command**:
```bash
redis-cli get v2:trainer:feedback:outcomes | python3 -c "
import sys, json
d = json.load(sys.stdin)
rows = d if isinstance(d, list) else d.get('rows', [])
reasons = {}
for r in rows[:50]:
    reason = r.get('quarantine_reason', 'UNKNOWN')
    reasons[reason] = reasons.get(reason, 0) + 1
print('Sample quarantine reasons:', reasons)
"
```

**Blocked by this gap**: Trainer learning, model improvement, paper performance validation

---

### GAP_P0_002: Paper Trading PnL Negative (-$253.49)

**Description**: Realized PnL is -$253.49 across 743 closed trades. Unrealized PnL is -$46.14. No positive edge has been demonstrated.

**Impact**: System cannot be considered ready for any scaling decision. Paper PnL must reach positive expectancy over a statistically significant sample before any live-readiness consideration.

**Evidence**:
- `v2:paper:ledger` → `realized_pnl_usd: -253.4863585220265`
- `v2:paper:ledger` → `unrealized_pnl_usd: -46.14`
- 743 closed trades, 456 accepted fills (historical), 462 blocked

**Root cause**: Likely combination of: deny_default blocking recent paper fills (system not generating new trades), and stale model without feedback reward signal.

**Resolution path**:
1. Resolve GAP_P0_001 (feedback quarantine) first
2. Once feedback flows, trainer will learn from outcomes
3. Allow 500-1000 new paper trades with feedback-informed model
4. Re-evaluate PnL and win rate

**Blocked by this gap**: Live-readiness consideration, capital scaling, performance review

---

## P1 — High Severity

### GAP_P1_001: Risk Gateway deny_default Blocking All Paper Fills

**Description**: All 130 orchestrator decisions per cycle are denied by the risk gateway (deny_default). This means the paper trader is not generating new fills. Open position count = 0. Current paper accounting reflects only historical trades.

**Impact**: System is in a frozen state. New paper positions cannot be opened. This is partly by design (live gate is blocked) but in paper shadow mode, some paper fills should still be allowed.

**Evidence**:
- Risk gateway heartbeat: 130/130 decisions = DENY
- Paper ledger: accepted_fills: 0, blocked_fills: 0 (no new attempts in current cycle)
- live_gate: blocked_human_only → deny_default for all decisions

**Context**: deny_default is EXPECTED when live gate is blocked. However, in pure paper mode, the risk gateway should allow paper-only fills with PAPER_ALLOW decisions. The current state may indicate the risk gateway is not issuing paper-only allows.

**Resolution path**:
1. Investigate whether paper-mode ALLOW decisions are being generated for paper-only fills
2. Check `v2:risk:gateway:paper_online_decisions` key type and content
3. If paper fills should proceed without risk gateway approval in shadow mode, verify orchestrator→paper path bypasses live risk gateway for paper-only mode

---

### GAP_P1_002: Trainer Heartbeat Has No TTL (Persistent Key)

**Description**: `v2:trainer:hybrid_cuda:heartbeat` has TTL = -1 (persistent key, no expiry). This means the key will never expire, so monitoring systems cannot detect trainer failure by key expiration.

**Impact**: Trainer health monitoring based on TTL will not work. If trainer stops, heartbeat remains stale indefinitely.

**Resolution path**: Trainer should write heartbeat with TTL (e.g., 300 seconds) so that stale detection works. Update `v2_native_cuda_trainer_persistent_loop.py` to set TTL on heartbeat.

---

### GAP_P1_003: Prediction Key for Key Symbols Has No TTL

**Description**: `v2:prediction:BTCUSDT:1h` has TTL = -1 (persistent, no expiry). Prediction keys should have TTL to indicate freshness.

**Impact**: Stale predictions may be used if trainer stops. Website may show stale predictions without any freshness warning.

**Resolution path**: Publisher should set TTL on prediction keys (e.g., 1200 seconds). Update `v2_all_timeframe_prediction_signal_price_target_publisher.py` to set TTL.

---

## P2 — Medium Severity

### GAP_P2_001: AICoin Credentials Missing (5 env vars)

**Description**: AICoin whale wall data is CREDENTIAL_BLOCKED. 5 environment variables are absent: AICOIN_ACCESS_KEY_ID, AICOIN_ACCESS_SECRET, AICOIN_API_KEY, AICOIN_API_SECRET, AICOIN_API_BASE_URL.

**Impact**: Whale wall order book data unavailable. This is an enrichment signal, not a core feature — system continues to operate without it, but signal quality is reduced.

**Resolution path**: Obtain AICoin credentials and add to `.env` (never to code or git).

---

### GAP_P2_002: LunarCrush Status Unknown

**Description**: LunarCrush social sentiment ingestor status not verified. Service running but data quality unknown.

**Resolution path**: Check `redis-cli ttl v2:altdata:lunarcrush:BTCUSDT` and verify data freshness.

---

### GAP_P2_003: Nansen Status Unknown

**Description**: Nansen on-chain analytics ingestor status not verified.

**Resolution path**: Check `redis-cli ttl v2:altdata:nansen:BTCUSDT` and verify data freshness.

---

## P3 — Low Severity

### GAP_P3_001: 1 Failed Systemd Service (Non-Critical)

**Description**: `ai-bot-v2-autonomous-no-manual-next-task-policy.service` is in FAILED state.

**Impact**: LOW — this service manages autonomous next-task scheduling, which is not critical to the trading pipeline.

**Resolution path**: `systemctl --user reset-failed ai-bot-v2-autonomous-no-manual-next-task-policy.service` and investigate failure cause.

---

### GAP_P3_002: Live Gate State Is Intentionally Stale

**Description**: live_gate:state has TTL = -1 and was generated 2026-06-12 (age > 1.6M seconds). This is intentional — the live gate state is manually managed, not auto-refreshed.

**Impact**: LOW — intentional design. Live gate should only be updated by operator action.

**Resolution**: None required. Document that live gate state is operator-managed and persistent by design.

---

### GAP_P3_003: ~28 Backend API Stub Routes

**Description**: Approximately 28 API routes are stub handlers that return empty or placeholder data. These are documented in `docs/api-gap-register.md`.

**Impact**: LOW — corresponding website pages show empty data but do not crash.

**Resolution path**: Implement stub routes incrementally as needed.

---

## Blockers by Subsystem

| Subsystem | Blocker | Priority |
|-----------|---------|---------|
| Trainer | Feedback quarantine | P0 |
| Paper Trader | Negative PnL | P0 |
| Risk Gateway | deny_default on all paper | P1 |
| Trainer Monitoring | No TTL on heartbeat | P1 |
| Prediction Monitoring | No TTL on prediction | P1 |
| AICoin Ingestor | Missing credentials | P2 |
| LunarCrush | Status unknown | P2 |
| Nansen | Status unknown | P2 |
| Systemd | 1 failed service | P3 |
| Live Gate | Stale (intentional) | P3 |
| Backend API | Stub routes | P3 |

---

## P0 Resolution Priority

**Fix in this order:**

1. **GAP_P0_001** — Diagnose feedback quarantine reason codes
2. **GAP_P0_001** — Run `v2_paper_outcome_memory_rebuild.py` if reason = TRUST_EPOCH_MISMATCH
3. **GAP_P0_001** — Verify consumable_row_count > 0
4. **GAP_P1_001** — Investigate paper-mode ALLOW decisions in risk gateway
5. **GAP_P0_002** — Allow 500+ new paper trades to accumulate
6. Re-audit trainer feedback and PnL after resolution
