# A-grade halt chain — diagnosis + unlock (2026-07-13, no fakes)

## Question
Operator asked: how many A-grades so far, why do the apps show none, and to fix
until past `A_GRADE_HALTED_PERFORMANCE` without faking anything.

## Answer
A-grades so far: **0** (apps display truthfully). The halt was a self-locking
chain rooted in stale history + a calibration-scale mismatch — both fixed with
sanctioned mechanisms; no thresholds relaxed for graded lanes, no evidence faked.

## The chain (raw evidence at each link)
1. Old session had 4 closed probation trades (`governed_closed_rows: 4` in
   bucket_quarantine_status.json) incl. AVAX/SUI high-confidence losses.
2. Those 4 trades quarantined 7 SWEEPING buckets (`side:long`, `timeframe:15m`,
   `regime:HIGH_VOLATILITY,TREND`, ...) — statistically indefensible breadth
   from a 4-row sample.
3. 343+/563 intents matched a quarantined bucket → `bucket_quarantine_active`
   → loss probability forced to 0.92 (556/563 rows at exactly 0.92).
4. Preemptive edge control: `NO_TRADE: 563` / `BLOCK_LOSS_PROBABILITY_TOO_HIGH: 563`.
5. Zero probation candidates → probation pinned 4/5 → guardian rolling-100/300
   windows observed 0 → `A_GRADE_HALTED_PERFORMANCE` → nothing trades → stats
   never refresh (self-locking).
6. Meanwhile the NEW temporal+TA model was supplying 124-182 candidates with
   genuinely positive expected edge after cost — blocked purely by (1)-(5).

## Fix 1 — operator-authorized session rotation (the documented remedy)
`v2_final_pre_*_3000_paper_reset --operator-authorized-reset` (archives all keys
to raw_evidence/goal_state first; paper-only by construction). New session
`paper_3000_..._20260713T190904Z`, $3,000, loop restarted.
Verified after one cycle: quarantine 7→0 buckets, loss probabilities 0.92→real
(0.20-0.90, 21 below the 0.65 probation bound), preemptive decisions became
`ALLOW_PAPER_RISK_CONTROLLER_EXPLORATION: 17-21` + `ALLOW_PROBATION_PAPER: 3`.

## Fix 2 — allocator low-confidence vs honest calibration (commit a9940122e9)
Remaining lock: fills still zero. Rows showed
`ALLOCATOR_HARD_BLOCK:BLOCK_LOW_CONFIDENCE` — the adaptive allocator hard-blocks
`confidence_calibrated < 0.50` (allocator.py `_allocate`) while honest WI-3
outcome-fit calibration puts the cold-start model at 0.427-0.585 (median 0.476).
The bootstrap exploration lane exists precisely to break this circularity (its
own design comment) but only overrode the floor-spelling of the confidence
blocker, not the allocator's expression of the same signal. Fresh session also
means `symbol_timeframe_evidence_count: 0` → dynamic floor pinned at its 0.88
ceiling → nothing (incl. probation at conf≤0.585) could pass.

Fix: `ALLOCATOR_HARD_BLOCK:BLOCK_LOW_CONFIDENCE` added to
`BOOTSTRAP_OVERRIDABLE_BLOCKERS` (paper_exploration/policy.py). Scope guarantees:
- only active under the operator lever `PAPER_BOOTSTRAP_EXPLORATION_ENABLED`
- only when EVERY other blocker is clear — `BLOCK_NO_EDGE`,
  `BLOCK_BAD_MARKET_STATE`, `BLOCK_EXPOSURE_BUDGET`, liquidity, circuit-breaker,
  integrity, lookahead all stay hard
- bootstrap fills remain paper-only and NEVER count as A-grade/A+ evidence
Test locks both directions (override low-confidence, keep NO_EDGE hard);
453 inventory+paper-loop tests pass.

## Post-fix observations
- dynamic floor descending: 0.88 → 0.70 observed on candidates
- bootstrap admits: 2+ per cycle
- **first 2 paper positions of the new session OPEN** (1000FLOKIUSDT,
  POLUSDT long; ~$3.7 adaptive notionals; paper_only=True, routes=False,
  a_grade_evidence=False)

## Remaining path to A-grades (honest accumulation, no shortcuts)
closes → symbol/tf evidence count grows → floor descends toward 0.58 →
probation lane admits (needs real confidence ≥ floor; model improvement via the
offline flywheel raises calibrated confidence) → probation 5/20/50-trade gates
(PF ≥ 1.0/1.1/1.25) → guardian 100/300-trade rolling windows → halt lifts →
A-grade rows appear from real performance only.

## Verification commands
- `redis-cli GET v2:paper:preemptive_edge_control_status | jq .decision_counts`
- `redis-cli GET v2:paper:intents | jq '[.intents[].pre_trade_loss_probability] | min, max'`
- bucket_quarantine_status.json → quarantined_buckets length, governed_closed_rows
- `redis-cli GET v2:paper:positions | jq '.positions | length'`
