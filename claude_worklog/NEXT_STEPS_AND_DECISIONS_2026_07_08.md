# Next Steps & Required Decisions — 2026-07-08

## Codex Alignment Note - 2026-07-08

This file is a historical Claude/Fable decision memo, not an approved
operational runbook. Its Redis counts, endpoint-health claims, feature counts,
win-rate claims, and readiness statements must be re-verified with current
read-only checks before use.

Do not run legacy ingestors, Redis expiry mutations, live exchange calls, test
orders, leverage changes, or margin-mode changes from this document without
explicit operator approval.

The current same-day path is provider-rate-limited:

- CoinGlass uses an endpoint registry, token-bucket limiter, per-endpoint cadence,
  and request budget.
- Moralis uses an endpoint registry, wallet/token/stream cadence, and compute-unit
  budget limiter; it must not poll every symbol every minute.
- Provider Redis keys and endpoint-to-feature mappings are explicit contracts.
- Dashboard/iOS panels must show actual payload status, not heartbeat-only green.
- Trainer, risk, orchestrator, allocator, paper, and live-dry-run consumers must
  receive provider context through the V2 provider feature bridge.
- Optional provider failures are not core-blocking.
- Live-ready cannot be marked from probation alone.

## Documents Created (All in `claude_worklog/`)

1. **COMPREHENSIVE_COINANK_LEGACY_V2_AUDIT_2026_07_08.md** (310 lines)
   - Full technical audit with all findings
   - Verified against Redis, source code, API call logs
   - Complete endpoint inventory, data flows, alternative analysis

2. **COINANK_AUDIT_TECHNICAL_FINDINGS_2026_07_08.md**
   - Detailed verification with Redis queries
   - Evidence trail: where each claim comes from
   - Cost-benefit calculations for provider strategies

3. **AUDIT_EXECUTIVE_SUMMARY_2026_07_08.txt**
   - One-page executive summary
   - Decision points clearly marked
   - Timeline and resource requirements

---

## Three Decisions Needed This Week

### Decision 1: CoinAnk Strategy

**RECOMMENDATION:** Keep CoinAnk + Add CoinGlass

| Option | Action | Cost | Risk | Result |
|---|---|---|---|---|
| **A (Current)** | Keep CoinAnk only | $99/mo | No redundancy | All CEX features |
| **B (Recommended)** | CoinAnk + CoinGlass | +$20/mo | Minimal | +40% features |
| **C (Bad)** | Replace with CoinGlass | -$79/mo | 70% feature loss | **AVOID** |
| **D (Worse)** | Multi-provider combo | $648+/mo | Still missing features | **AVOID** |

**Why Option B:**
- CoinGlass: 30% coverage (liquidation viz + reserves)
- Zero feature loss from CoinAnk (still 100%)
- +20% cost for +40% new insight
- Low risk, high reward

**Approval Needed:**
```
[ ] Approve Option B (CoinAnk + CoinGlass, +$20/month)
```

### Decision 2: V2 Rebuild Roadmap

**RECOMMENDATION:** Execute 8-Week Rebuild Plan with Phase Gates

**Phase A (Week 1-2):** Feature Pipeline Restoration
- Target: 562-field unified features
- Includes: TA adapter, CoinAnk integration, regime state machine

**Phase B (Week 3-4):** ML Trainer Porting  
- Target: Predictions generating again
- Includes: PPO, MASA, checkpoint loading

**Gate:** Don't proceed to Phase C until Phase B passes paper trading

**Phase C (Week 5-6):** Microstructure & Advanced Features
- Target: Entry timing + whale tracking
- Includes: WebSocket ingestor, orderbook, TokenMetrics

**Phase D (Week 7-8):** Full Integration & Testing
- Target: live-canary review readiness while live remains blocked

**Approval Needed:**
```
[ ] Approve 8-week rebuild roadmap
[ ] Approve phase-gating strategy (B before C, all before D)
```

### Decision 3: Resource Allocation

**REQUIREMENT:** 1-2 Engineers, Full-Time, 8 Weeks

| Resource | Estimate | Required |
|---|---|---|
| **Development Time** | 1-2 FTE × 8 weeks | YES |
| **GPU Hardware** | Existing (4-6GB VRAM) | HAVE |
| **Redis** | Existing (21GB) | HAVE |
| **Provider Budget** | +$20/month (CoinGlass) | YES |
| **Testing Hardware** | Existing | HAVE |

**Approval Needed:**
```
[ ] Allocate 1-2 engineers full-time for 8 weeks
[ ] Approve $20/month additional provider cost
```

---

## Immediate Actions (This Week)

### Action 1: Verify CoinAnk Runtime Truth (read-only first)

**Who:** Any engineer  
**When:** Today  
**How:**
```bash
# Read-only examples only. Runtime repair/restart requires explicit operator approval.
redis-cli --scan --pattern 'features:coinank:*' | wc -l
redis-cli GET 'meta:coinank:last_update'
redis-cli --scan --pattern 'latest:coinank:*' | wc -l
redis-cli --scan --pattern 'features:coinank_endpoint:*' | wc -l
```

**Expected:**
- Current truth artifact records actual key counts and freshness
- Provider status is not green from heartbeat alone
- Any runtime repair is handled as an approval-gated change

**Verification:**
```bash
PYTHONPATH=v2/backend python -m app.cli.v2_provider_scheduler_status --help
PYTHONPATH=v2/backend python -m app.cli.v2_same_day_production_cutover_status --help
```

### Action 2: Build TA Flat Hash Adapter (4-6 hours)

**Who:** ML engineer or backend engineer  
**When:** This week  
**What:**
```
Input:  v2:technical_analysis:{SYM}:{TF} (JSON blob)
        { "indicators": { "RSI": { "value": 65 }, ... } }

Output: ta:{SYM}:{TF} (160-field Redis HASH)
        RSI → 65
        MACD → 0.0012
        BB_UPPER → 45230
        ... (160 fields total)
```

**Why:** Trainer expects flat hash, not nested JSON

**Expected:**
- +160 feature fields
- Full TA integration without rewriting legacy trainer code

### Action 3: Implement TTL Management Through Reviewed Code (1 hour estimate)

**Who:** DevOps or backend engineer  
**When:** This week  
**What:**
Add TTL hygiene to reviewed V2 services/scripts and validate with read-only
coverage checks. Do not use ad hoc `redis-cli KEYS ... EXPIRE ...` mutation from
this memo.

**Why:** Prevent stale data corruption from keys that never expire

**Expected:**
- Automatic cleanup after 24 hours
- Better data hygiene

---

## Implementation Timeline

```
Week 1:
  Mon: Run read-only CoinAnk/provider truth checks + validate TA adapter path
  Tue-Wed: TTL management implementation through reviewed code
  Thu-Fri: Begin Phase A (feature pipeline)

Week 2:
  Continue Phase A
  Integration testing with CoinAnk data
  
Week 3-4:
  Phase B (ML trainer)
  
Week 5-6:
  Phase C (microstructure)
  
Week 7-8:
  Phase D (integration + testing)
```

---

## Success Criteria

### Quick Wins (This Week)
- [ ] CoinAnk/provider actual-data truth checked with current read-only evidence
- [ ] Any CoinAnk runtime repair approved explicitly before execution
- [ ] TA adapter built (160 fields in legacy format)
- [ ] TTL management enabled through reviewed code (24h expiry)

### Phase A (Week 2)
- [ ] 562-field unified features building
- [ ] CoinAnk data flowing through pipeline
- [ ] No loss of existing liquidation features

### Phase B (Week 4)
- [ ] Predictions generating in `v2:prediction:{SYM}:{TF}`
- [ ] Paper trading producing signals
- [ ] Win rate >50% on backtests

### Phase C (Week 6)
- [ ] Microstructure data flowing
- [ ] TokenMetrics integrated
- [ ] Entry timing improved

### Phase D (Week 8)
- [ ] Full end-to-end test passing
- [ ] Paper trading 24/7 without errors
- [ ] Live-canary review packet accepted while live remains blocked

---

## Risk Mitigation

### If Timeline Slips

**Contingency 1 (Week 2 buffer):** +1 week per phase if needed
- Total: 11 weeks vs 8 weeks
- Same resource requirements

**Contingency 2 (Phased Launch):** Go live with Phase A+B only
- Can trade with limited features while Phase C/D finish
- Acceptable risk: lower sharpe, smaller position sizing

**Contingency 3 (Resource Boost):** Add 3rd engineer for parallel work
- Phase A + Phase C can run in parallel if needed
- Reduces timeline to 6-7 weeks

### If CoinAnk Ingestor Fails

**Fallback:** Use stale Redis keys
- Loss: Recent liquidation data (critical but recoverable)
- Workaround: Manual CoinAnk API calls for critical features
- Recovery: Fix ingestor + restart (1-2 hours max)

### If Trainer Porting Exceeds 2 Weeks

**Fallback:** Use legacy trainer directly
- Copy trainer from `AI BOT - Legacy` to V2
- Compatibility bridge only; performance must be re-validated with current data
- Later: Rewrite in V2 framework when time permits

---

## Communication Plan

**Stakeholders:**
- [ ] Risk team (need Phase B approval for paper trading)
- [ ] Finance team (budget: +$20/month)
- [ ] Ops team (GPU/Redis resource allocation)
- [ ] Trading team (expect signals by Week 4)

**Weekly Status Updates:**
- Monday: Week plan
- Friday: Week recap + blockers

**Approval Meeting:**
- Needed: This week
- Decisions: All three (CoinAnk, timeline, resources)
- Duration: 30 minutes

---

## Questions to Answer

1. **CoinAnk Decision:** Do we add CoinGlass? (Recommended: YES)
2. **Timeline Decision:** Do we commit to 8 weeks? (Realistic with 1-2 FTE)
3. **Resource Decision:** Do we have 1-2 engineers available now?
4. **Contingency Decision:** If timeline slips, do we add resources or extend date?
5. **Launch Decision:** Do we go live with A+B only if time is short?

---

## Sign-Off Required

```
Decision 1 (CoinAnk Strategy):
  [ ] Approved - Add CoinGlass (+$20/month)
  [ ] Rejected - Keep CoinAnk only
  [ ] Other - ________________

Decision 2 (V2 Rebuild):
  [ ] Approved - 8-week roadmap with phases A-D
  [ ] Rejected - Other approach
  [ ] Conditional - If resources available

Decision 3 (Resources):
  [ ] Approved - 1-2 engineers, 8 weeks
  [ ] Approved with contingency - Add 3rd engineer if needed
  [ ] Denied - Other constraints

Signed: ________________
Date: 2026-07-08
```

---

## Appendix: Who Does What

### Quick Wins (This Week)

**CoinAnk Actual-Data Truth Check:**
- Backend engineer or DevOps
- Command: read-only Redis/provider status checks first
- Runtime repair/restart: requires explicit operator approval

**Build TA Adapter (4-6 hrs):**
- ML engineer or backend engineer
- Task: JSON blob → 160-field hash conversion
- Framework: Python, Redis operations

**TTL Management (1 hour):**
- DevOps or backend engineer  
- Task: Set expiry on all CoinAnk keys
- Automation: Script for periodic runs

### Phase A (Week 1-2)

**Feature Pipeline Lead:**
- ML engineer or senior backend engineer
- Task: Coordinate 560+ feature field restoration
- Blocks: Phase B won't start without this

### Phase B (Week 3-4)

**Trainer Lead:**
- ML engineer with PyTorch/RL experience
- Task: Port PPO and MASA models
- Blocks: Phase C won't start without this

### Phase C (Week 5-6)

**Integration Lead:**
- Backend engineer
- Task: WebSocket ingestors, cross-exchange aggregation
- Parallel with Phase B acceptable

### Phase D (Week 7-8)

**Testing Lead:**
- QA engineer or senior backend engineer
- Task: End-to-end validation, live-canary review packet with live still blocked

---

**Document Date:** 2026-07-08  
**Ready for:** Decision Meeting  
**Next:** Schedule approval meeting with stakeholders
