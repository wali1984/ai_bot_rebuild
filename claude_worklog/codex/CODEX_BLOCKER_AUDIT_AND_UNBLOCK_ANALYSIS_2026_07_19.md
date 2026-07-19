# Independent Read-Only Audit + Unblock Analysis of Codex's Stated Blockers

Author: Claude main session (independent audit lane; did NOT edit Codex code)
Date: 2026-07-19 (UTC; guardian check 2026-07-19T04:29Z)
Method: READ-ONLY — code reads, `systemctl show`, Redis GET, `/api/v2/paper/status`, `.venv/bin/pytest`.
No code edits, no Redis writes, no process changes, no service flips. Live gate BLOCKED throughout.
Scope: verifies the 9 blockers Codex reported and gives an unblock path for each. Verdict up front:
**this is a disciplined fail-closed rollout, not a stall.** Codex's blocker list is accurate.

## Reconciliation with my earlier note
Codex is correct that the paper loop is NOT dead. Verified:
`systemctl --user show ai-bot-v2-trade-management-paper-loop.service -p NRestarts,ActiveState` →
`NRestarts=0`, `ActiveState=active`, started 2026-07-18 20:45:21 EDT. My earlier "dead" reading was the
PRIOR instance (Main PID 1641118, exited 18:12 EDT); a new instance came up at 20:45 and has run clean
since. Correction accepted. Also: the zero-candidate state I flagged earlier is LARGELY the deliberate
fail-closed hold below, not (only) a `decision.py` defect — this supersedes the "generator bug" framing
in CODEX_CANDIDATE_SUPPLY_STARVATION_CRITICAL_PATH.md P1a.

## THE KEYSTONE: trainer provenance (#1) gates the cascade #1→#2→#3→#6→#7
These are ONE dependency chain, not five independent problems:
```
#1 PIT/finality receipts incomplete (446 feature slots / 1,784 model inputs)
   └─ #3 five trainer/replay/guardian services held fail-closed  (CORRECT posture)
        └─ #2 old feature worker still on unsafe v1 snapshots — restart deferred  (CORRECT)
             └─ #6 feeder held → 0 A-grade rows, 0 candidates, 25 shadow-only allocator passes
                  └─ loop cannot trade → #7 evidence frozen: 92 closes, PF 0.658, historical G10
```
Evidence for the tail of the chain (`/api/v2/paper/status`, read-only):
- `summary.intents_accepted = 0` AND `summary.intents_blocked = 0` (nothing reaches the loop).
- `a_grade_blocker_truth.a_grade.closest_gap_reason = NO_A_GRADE_RUNTIME_SUPPLY`.
- `a_grade_blocker_truth.preemptive.candidate_count = 0`; `paper_learning_feeder.fresh_exploration_candidates = 0`.
- Guardian: G10 = 46 invariant violations on pre-fix rows; G13 = -18.126 nw bps; G14 = PF 0.658 — all on
  the frozen 92-trade set (`current_trades=92, historical_trades=0`).
- Feature counts confirmed in the trainer telemetry surface: FEATURE COUNT 446, TENSOR INPUT DIM 1,784.

**Unblock (#1 is the master):** finish the immutable PIT/finality receipt contract so each of the 446 slots
→ 1,784 inputs carries an exact verifiable receipt (source event id + finality timestamp + content hash).
Then, and only then:
- **#2** — replace/restart the feature worker so it emits receipt-backed (not v1) snapshots. Foundation is
  already committed: `249f461081` durable WSS label producer, `1cd167cf56` durable PIT label archive,
  `6446c40924` serialized canonical label writers. Restarting the v1 worker before this would re-poison the
  trainer — Codex's hold is right.
- **#3** — flip the five fail-closed services active **one verified slice at a time** (matches Codex's
  "commit and push each verified repair slice"). Do not bulk-release.
- **#6/#7 are CONSEQUENCES** — they self-resolve once the feeder is receipt-clean and the loop trades again.
  Do NOT force candidate supply or "fix expectancy" upstream of provenance; that just reintroduces the
  unsafe-snapshot problem #1 exists to prevent.

## INDEPENDENT of provenance — two leverage bugs that can land NOW (#4, #5)

### #4 — VERIFIED, safety-critical: cap SELECTED instead of INTERSECTED
Location: uncommitted `v2/backend/app/services/adaptive_capital_allocator/dynamic_envelope.py:182-189`:
```python
raw_leverage_ceiling = (
    symbol_leverage_ceiling(symbol)   # SOL/LTC/XRP=50, alt=20, BTC/ETH=75
    if str(symbol or "").strip()
    else PAPER_MAX_LEVERAGE            # 75
)
leverage_ceiling = _finite_float(raw_leverage_ceiling)
```
This picks the symbol ceiling as the SOLE cap; it never intersects with the other binding envelopes
(operator/global `PAPER_MAX_LEVERAGE`, `cfg.max_leverage`, the dynamic risk envelope, the liquidation-safe
cap). So a SOL candidate resolves to 50x even when a tighter envelope binds at 20x — exactly Codex's
description. NOTE: the committed `paper_trade_management/leverage_recommendation.py:234` is already correct
(`min(configured_cap, symbol_ceiling, liquidation_safe_ceiling)`); the defect is only in the newer
allocator envelope path.
**Fix pattern:** take the narrowest binding cap —
`leverage_ceiling = min(symbol_ceiling_or_global, PAPER_MAX_LEVERAGE, configured_cap, dynamic_envelope_cap, liquidation_safe_cap)`.
**Regression test spec (add to test_adaptive_leverage_margin_ramp.py):** symbol=SOL (ceiling 50) with a
20x binding envelope MUST resolve effective_leverage ≤ 20, never 50; symbol=BTC (75) with global cap 20
MUST resolve ≤ 20. Priority: HIGHEST of the two — it is a real over-leverage exposure even in paper.

### #5 — design refinement: scale with edge-lower-bound MAGNITUDE
Dynamic leverage currently treats every positive edge lower bound alike rather than scaling with its
magnitude. The correct pattern already exists in committed `leverage_recommendation.py:286-291`
(`recommended_leverage = 1 + continuous_market_quality*(ceiling-1)`, where quality is an edge/ATR energy
ratio). The allocator envelope needs the same magnitude term wired into its `edge_evidence` input rather
than a binary positive/not-positive gate, so a larger positive lower bound earns proportionally more of
the envelope. Independent of #1; can land with #4.

## #8 — effectively resolved
Removing the unverifiable post-commit timestamp was the correct call (exactly the unfalsifiable-claim class
the evidence-integrity rule forbids). 122 focused tests green + independent review in flight is a clean
closeout; no further unblock beyond letting the review land. **Watch item:** confirm the removal left no
dangling reference in the guardian CG-F049/F050 evidence chain (G03), or G03 stays red on a broken pointer.

## Test health of the uncommitted working set (read-only, `.venv/bin/pytest`)
- allocator + leverage lane: 137/137 green.
- broader ptm/edge lane: 220/221 — 1 red:
  `test_lifecycle.py::test_position_from_fill_sets_policy_activated_at_for_adaptive_policy`
  (expects `policy_activated_at == ...10:00:05Z`, got `...10:00:00Z`; 5s activation-timestamp gap).
  Must be green before the 4,329-line allocator rework commits.

## Recommended sequencing (read-only recommendation; execution is Codex/operator)
1. **NOW:** land #4 (over-leverage safety) + #5 (magnitude scaling) — independent of everything, lowest
   risk, removes tail exposure before the loop ever sizes up. Fix the 1 red lifecycle test, then commit
   the allocator rework slice.
2. **Then:** complete #1 receipt contract; flip the 5 services (#3) and swap the feature worker (#2)
   one verified slice at a time. This is Codex's stated plan — keep it slice-gated.
3. Only after the feeder is receipt-clean does #6 resolve → new coherent, positive-EV closes accumulate
   → #7 evidence improves → G10/G13/G14 can HONESTLY recover.
4. **Operator:** authorize `tools/g10_capital_invariant_repair.py` for the 46 historical rows (reversible,
   G08-safe). This is cosmetic cleanup of OLD data; the real recovery signal is the NEW closes.

## Confidence & missing evidence
- HIGH confidence: #4 bug (read the code), loop-running/#9 (`NRestarts=0`), candidate starvation
  (`intents_accepted=0`), feature counts (446/1,784), guardian gate values.
- MODERATE: #1/#2/#3 receipt-contract completeness is Codex's design claim; I cannot fully verify receipt
  presence per slot read-only without reading Codex's in-flight trainer code (Codex's lane).
- NOT verifiable read-only: whether `ppo_on_policy_rows` is climbing post-`a87029321d` (not surfaced in
  `/api/v2/paper/status`); the exact provenance-gate that suppresses the exploration feeder.

## Cross-refs
- claude_worklog/codex/CODEX_CANDIDATE_SUPPLY_STARVATION_CRITICAL_PATH.md (supersede P1a framing per above)
- claude_worklog/codex/CODEX_PPO_ON_POLICY_STARVATION_FINDING.md ; CODEX_PER_SYMBOL_LEVERAGE_ENVELOPE_HANDOFF.md (landed)
- claude_worklog/guardian_runtime_validation/CG_F049_F050_RUNTIME_VALIDATION_2026_07_17.md (WQ-R34)
