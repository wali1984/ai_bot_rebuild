# Strategy-Supply Independent Review Checkpoint — 2026-07-23T04:36:28Z

## Decision

**Runtime deployment remains NO-GO.** The cumulative authority tip is the one
correct integration target, and its directly affected regression surface is
green, but the current contract intentionally produces observation-only
research rows. Starting it would not restore canonical candidate, paper-fill,
trainer, leverage, or margin flow.

This checkpoint rejects a cosmetic activation. Authority flags must not be
flipped until the retained input and published output bytes are independently
receipted and verified.

## Immutable integration target

- Branch: `codex/strategy-authority-remediation-20260721`
- Reviewed tip: `4ed80b57c9e823e31be45510c6318f0d832eddc6`
- Upstream divergence before this checkpoint: `0 ahead / 0 behind`
- Cumulative ancestry:
  `f06277824e -> f0ce93da8e -> 8e7be099a0 -> 4fd8e1dadf -> 4ed80b57c9`
- The sibling optional-input commit `922d860c3b` is patch-identical to
  `4fd8e1dadf` and must not be applied again.

## Evidence counts

- Strategy branches inspected: **4/4**
- Relevant commit nodes mapped: **6**
- Cumulative files compared: **12**
  - production modules: **6**
  - test modules: **4**
  - prior evidence documents: **2**
- Source test definitions in the cumulative test surface: **96**
- Collected affected cases executed: **110/110 passed**
- Production modules compiled: **6/6**
- Commit-range whitespace errors: **0**
- Systemd units inspected: **1**
- Services started/restarted: **0**
- Redis writes: **0**
- Exchange calls/orders/leverage/margin mutations: **0**
- Screenshots/builds/routes inspected: **0/0/0**
- Runtime blockers remaining: **9**

## Runtime blockers

1. The publisher unit is inactive and runs the mutable repository with a
   relative virtual-environment path; it has no immutable release drop-in.
2. The exact closed-OHLCV read has strong schema, finality, continuity, byte
   hash, and clock checks but no independent post-commit receipt/CAS proof.
3. Published hypothesis rows keep output `available_at=None` because no
   post-commit readback receipt exists.
4. Consequently every row remains consumer-ineligible, trainer-ineligible,
   and unauthorized for paper filling.
5. CoinGlass, Moralis, liquidation levels, order book, tape, trust, FVG,
   zones, and cached confluence are deliberately masked pending their own
   retained-artifact resolvers.
6. A+ inventory correctly maps these observations to `NO_TRADE`, denies
   risk/orchestrator/allocator authority, and nulls notional, leverage, and
   margin fields.
7. Strategy economics still contain fixed market-sensitive constants that
   require a separate causal adaptive-calibration slice.
8. The symbol universe is resolved once before the loop; runtime universe
   changes currently require restart.
9. Cycle failure timestamps are backdated, and research-feedback finality
   accepts a missing boolean. The final quarantine prevents trainer leakage,
   but both defects must be corrected before promotion.

## Point-in-time result

The cumulative code does enforce exact binary closed-window reads, supported
symbol/timeframe ABI, final-candle boundaries, continuity, finite TA, no zero
fill, and this clock order:

```text
feature_cutoff <= source_available_at <= read_observed_at
               <= computed_available_at <= decision_time
```

It also correctly refuses to claim an output availability time before the
output exists. No MASA/PPO ordering assertion is made because these research
rows are prevented from entering the trainer lane.

## Exact resume point

Implement the missing receipt boundary as a separate focused branch:

1. bind each exact closed-OHLCV value to an independent post-commit readback
   receipt produced by every canonical writer;
2. make the causal strategy resolver verify receipt bytes, digest, revision,
   writer identity, and clock order against its one exact read;
3. publish hypotheses through a post-commit readback receipt and expose an
   output `available_at` only from that receipt;
4. admit only receipt-verified native closed-candle hypotheses to a tightly
   bounded paper exploration path while keeping every optional provider masked;
5. add adversarial mutation, stale/future clock, unfinished-candle,
   writer-collision, and missing-receipt tests; and
6. only then create an immutable unit and perform bounded runtime proof.

Do not lower economic/risk gates, synthesize provider context, or promote
research feedback into PPO/MASA to create supply.

## Verification command

```bash
PYTHONPATH="$PWD" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/pytest -q \
  v2/backend/tests/unit/cli/test_v2_a_plus_candidate_inventory.py \
  v2/backend/tests/unit/cli/test_v2_strategy_supply_publish_hypotheses.py \
  v2/backend/tests/unit/services/strategy_supply/test_edge_hypothesis_generator.py \
  v2/backend/tests/unit/services/strategy_supply/test_feedback_maturation.py \
  --maxfail=1 --tb=short
```
