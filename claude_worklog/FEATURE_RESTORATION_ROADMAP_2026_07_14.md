# FEATURE RESTORATION ROADMAP — Get Adaptive System Producing Trades

## GOAL
Restore 154 missing features → improve data coverage from 67.7% to 95%+ → enable trainer promotion → unlock candidate flow → accumulate trades toward A-grade unlock

## CRITICAL PATH (Feature Restoration)

### Phase 1: Quick Wins (High Impact, < 30 min)

**1.1: Enable Moralis Smart Money Data (6 features)**
- Status: Provider loop running BUT data is 10+ days old
- Fix: Check if MORALIS_API_KEY is set; if yes, restart provider loop
- Expected impact: +6 features, smart money flow signals
- Time: 5 min

**1.2: Restore Aicoin Features (8 features)**
- Status: Should be available from aicoin provider
- Fix: Verify aicoin provider is in feature pipeline, populate scores
- Expected impact: +8 features, market activity + signals
- Time: 10 min

**1.3: Restore DeFiLlama Features (3 features)**
- Status: TVL momentum, liquidity data
- Fix: Ensure defillama feature bridge is wired
- Expected impact: +3 features, protocol health
- Time: 5 min

**1.4: Restore Surf Features (2 features)**  
- Status: Market price signals
- Fix: Check surf_score population in pipeline
- Expected impact: +2 features, market regime
- Time: 5 min

**Subtotal Quick Wins: 19 features (+4%), 25 min**

### Phase 2: Medium Effort (Medium Impact, 30-90 min)

**2.1: Restore Santiment Features (14 features)**
- Status: Dev activity, social signals, onchain activity
- Features: dev_activity, social_volume, whale_activity, sentiment, onchain_activity, exchange_inflow, supply_on_exchanges
- Fix: Verify santiment provider integration, throttle vs API rate limit
- Expected impact: +14 features, on-chain health
- Time: 30 min

**2.2: Verify Nansen Features (presence flag)**
- Status: Institutional flow data
- Fix: Ensure nansen_presence boolean is populated
- Expected impact: +1 feature, institutional sentiment
- Time: 10 min

**2.3: Restore Legacy Provider Features (~80 features)**
- Status: Various providers (fear-greed, news attention, altdata confluence, etc.)
- Fix: Audit feature spec against legacy, re-enable missing sources
- Expected impact: +80 features, ensemble diversity
- Time: 40 min

**Subtotal Medium Effort: 95 features (+20%), 80 min**

### Phase 3: Integration & Validation (30 min)

**3.1: Verify Feature Freshness**
- Check all 95 new features are < 5 min old
- Restart any stale providers
- Time: 15 min

**3.2: Verify Data Coverage**
- Retrain model on 1 cycle
- Check data_coverage_percent reaches 90%+
- Check validation loss improvement
- Time: 15 min

**Subtotal Phase 3: 30 min**

## TOTAL EFFORT: 2.5 hours to 95% feature coverage

## Expected Outcomes After Restoration

| Metric | Before | Target | When |
|--------|--------|--------|------|
| Missing Features | 154 | <20 | After Phase 2 |
| Data Coverage | 67.7% | 95%+ | After Phase 3 |
| Validation Loss | REGRESSING | Improving | After model cycle |
| Model Status | INFERENCE_ONLY | TRAINING | After Phase 3 |
| Promotion Status | BLOCKED | ALLOWED | +1 cycle after validation improves |
| Candidate Confidence | NULL (0%) | 80%+ populated | After Phase 3 |
| Candidate Acceptance | 0% | 20%+ (depends on edge) | +2 cycles |
| Trade Accumulation | 8 trades/1h | 30+ trades/6h | +6 hours |

## Sequencing & Dependencies

```
Phase 1 (Quick Wins)
  ├─ Moralis restart (5 min)
  ├─ Aicoin enable (10 min)
  ├─ DeFiLlama enable (5 min)
  └─ Surf enable (5 min)
        ↓
Phase 2 (Medium Effort) - Can start while Phase 1 propagates
  ├─ Santiment features (30 min)
  ├─ Nansen integration (10 min)
  └─ Legacy provider audit (40 min)
        ↓
Phase 3 (Validation)
  ├─ Feature freshness check (15 min)
  └─ Model retraining + validation (15 min)
        ↓
RESULT: Trainer promotion allowed, trades accumulate
```

## Success Criteria

- [ ] data_coverage_percent ≥ 90%
- [ ] validation_loss is decreasing (not regressing)
- [ ] checkpoint_promotion_allowed = true
- [ ] effective_trainer_mode = TRAINING or TRAIN_AND_PREDICT
- [ ] raw_confidence field populated in ≥80% of candidates
- [ ] pre_trade_expected_cost fields populated in ≥80% of candidates
- [ ] paper loop accepting ≥5% of candidates (not 0%)
- [ ] Trades closing again (trend toward 100+ for A-grade)

## Risk Mitigation

**Risk 1:** API rate limits on providers
- Mitigation: Stagger provider restarts by 10 sec, monitor quotas
- Fallback: Disable lowest-ROI providers, focus on high-impact (Moralis, Santiment, Aicoin)

**Risk 2:** Data freshness lags
- Mitigation: Check timestamps on each provider, investigate backlog
- Fallback: Run data collection cycle twice before retraining

**Risk 3:** Model validation loss continues to regress
- Mitigation: Check that feature quality is actually improved (spot-check)
- Fallback: Revert to last good checkpoint, re-enable with fresh features

## Post-Restoration Monitoring

After Phase 3, monitor for 3 cycles:
1. **Cycle 1:** Validation loss should trend down (not plateau)
2. **Cycle 2:** Promotion should be allowed
3. **Cycle 3:** Candidates should have confidence, paper loop should accept trades

If any step fails, rollback and investigate the specific provider/feature.

---

**Next Action:** Start Phase 1 (Moralis restart, provider enables)
**Owner:** Claude Code
**Target Completion:** Within 3 hours of starting Phase 1
