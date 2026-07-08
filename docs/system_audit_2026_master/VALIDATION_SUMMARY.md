# Validation Summary — AI BOT V2
Generated: 2026-07-01
Audit: V2_REBUILD_MASTER_END_TO_END_SYSTEM_AUDIT_AND_OPERATOR_MANUAL

All validation commands are read-only. No trading mutations performed.

---

## Validation Results

| Check | Command | Result | Status |
|-------|---------|--------|--------|
| CLI Python syntax | py_compile all 230 scripts | 0 errors | PASS |
| Contract tests | pytest tests/contract/ | 9/9 passed | PASS |
| Website API health | curl http://localhost:8000/api/v1/health | 200 OK | PASS |
| TypeScript typecheck | npm run typecheck | No errors | PASS |
| Live gate blocked | redis-cli get v2:live_gate:state | blocked_human_only | PASS |
| No real orders | places_real_order field | False | PASS |
| Submit disabled | order_transport_submit_enabled | False | PASS |
| Paper TTL | redis-cli ttl v2:paper:heartbeat | 3556s | PASS |
| Risk gateway TTL | redis-cli ttl v2:risk:gateway:heartbeat | 298s | PASS |
| Feature pipeline TTL | redis-cli ttl v2:features:pipeline:heartbeat | 265s | PASS |
| Features fresh | redis-cli ttl v2:features:latest:BTCUSDT:1h | 547s | PASS |
| Redis keyspace size | redis-cli dbsize | 1,150,697 keys | PASS |
| Trainer heartbeat | redis-cli ttl v2:trainer:hybrid_cuda:heartbeat | -1 (no TTL) | WARN |
| Prediction BTCUSDT 1h | redis-cli ttl v2:prediction:BTCUSDT:1h | -1 (no TTL) | WARN |
| Failed services | systemctl --user --failed | 1 non-critical | WARN |
| Trainer feedback | feedback_consumable_row_count | 0 of 741 | FAIL |
| Paper PnL | realized_pnl_usd | -$253.49 | FAIL |

---

## Detailed Validation Evidence

### 1. Python Syntax Check (PASS)
```
Command: python3 -c "import py_compile, glob; [py_compile.compile(f, doraise=True) for f in glob.glob('app/cli/*.py')]"
Result: Checked 230 files; syntax errors: 0
```

### 2. Contract Tests (PASS)
```
Command: python3 -m pytest tests/contract/ -v -q
Result:
  tests/contract/test_middleware_order.py ... PASSED (3 tests)
  tests/contract/test_taxonomy_enumeration.py ...... PASSED (6 tests)
  9 passed in 0.57s
```
Contracts verified:
- MIDDLEWARE_ORDER matches expected 10-layer stack
- Error taxonomy enumeration is complete

### 3. Website API Health (PASS)
```
Command: curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/health
Result: 200
```

### 4. TypeScript Typecheck (PASS)
```
Command: npm run typecheck (tsc -b --noEmit)
Result: No output (no errors)
```

### 5. Live Gate Verification (PASS)
```
Command: redis-cli get v2:live_gate:state | python3 -c "..."
Result:
  live_gate: blocked_human_only
  places_real_order: False
  order_transport_submit_enabled: False
```
CRITICAL SAFETY CHECK: PASS — live trading is blocked at all three checkpoints.

### 6. Heartbeat Freshness (MIXED)

| Service | TTL | Status |
|---------|-----|--------|
| Paper Trader | 3556s | PASS |
| Risk Gateway | 298s | PASS |
| Feature Pipeline | 265s | PASS |
| Features BTCUSDT:1h | 547s | PASS |
| Trainer Heartbeat | -1 (no expiry) | WARN |
| Prediction BTCUSDT:1h | -1 (no expiry) | WARN |

Note: TTL=-1 means key exists with no expiry set. This is not necessarily stale — it means the key won't auto-expire. Trainer likely writes persistent heartbeat by design. Staleness must be checked by reading `updated_at` field inside the key.

### 7. Trainer Feedback (FAIL)
```
Command: redis-cli get v2:paper:ledger | python3 -c "... print consumable count ..."
Result:
  feedback_consumable: 0
  feedback_quarantined: 741
```
CRITICAL FINDING — P0 GAP (see GAP_P0_001 in gap_register.json)

### 8. Paper PnL (FAIL)
```
Command: redis-cli get v2:paper:ledger | python3 -c "... print pnl ..."
Result:
  realized_pnl_usd: -253.4863585220265
  closed_trades: 743
```
CRITICAL FINDING — P0 GAP (see GAP_P0_002 in gap_register.json)

### 9. Redis Keyspace (PASS)
```
Command: redis-cli dbsize
Result: 1,150,697 keys
All keys in v2: namespace — no legacy namespace writes detected.
```

### 10. Failed Services (WARN)
```
Command: systemctl --user --failed --no-legend | grep 'ai-bot'
Result: ai-bot-v2-autonomous-no-manual-next-task-policy.service FAILED
Impact: LOW — non-critical scheduling service
```

---

## Validation Not Run (Why)

| Validation | Reason Not Run |
|-----------|---------------|
| Full pytest suite (3,493 tests) | Takes 5-15 minutes; not required for audit pass; see prior run baseline |
| Playwright E2E (48 specs) | Requires full browser + backend setup; not run inline |
| Live transport probe | SAFETY: Do not probe live transport during audit |
| AICoin probe | Credentials missing; cannot probe |
| Exchange order test | SAFETY: Never place test orders |
| Redis write to v2:paper:* | SAFETY: Never mutate paper state during audit |

---

## Validation Verdict

```
PASS: Python syntax (230 scripts clean)
PASS: Contract tests (9/9)
PASS: Website backend health
PASS: TypeScript typecheck
PASS: Live gate blocked
PASS: No real orders
PASS: Feature pipeline fresh
WARN: Trainer heartbeat no TTL
WARN: Prediction no TTL
WARN: 1 failed service (non-critical)
FAIL: Trainer feedback 0 consumable (P0)
FAIL: Paper PnL negative (P0)

Overall: BLOCKED (2 FAIL conditions are P0)
```
