# Independent Runtime Validation — CG-F049 (short-inversion) & CG-F050 (capital-invariant split-brain)

Date: 2026-07-17 (guardian check 2026-07-18T01:04Z)
Validator: Claude main session (independent of Codex fix lane)
Method: READ-ONLY Redis reads of current paper state. No mutation, no order placement. Live gate BLOCKED.
Running paper loop under test: **PID 2215061, started Fri Jul 17 16:00:26 2026** (v2_trade_management_paper_loop --loop).

## Why this task
Guardian G03 lists CG-F049 and CG-F050 as `FIX_APPLIED_PENDING_INDEPENDENT_RUNTIME_VALIDATION`.
I am the independent validator. This is in-lane (validation, not editing Codex code), non-colliding,
non-mutating. Result determines whether the fixes are actually active or the running process predates them.

## Verification command (reproducible)
Read-only script over `v2:paper:positions` + `v2:paper:closed_trades`; per-row check of the invariant
`gross_notional_usd ~= allocated_margin_usd × effective_leverage` (tol $0.02), bucketed by exit timestamp
and by subclass; plus LONG/SHORT count + net PnL split.

## CG-F050 (capital-invariant split-brain = hidden leverage) — RUNTIME VALIDATION: **NEGATIVE (still pending)**
- **Both current OPEN positions are COHERENT**: MANAUSDT 76.22 = 38.11 × 2.0; ARBUSDT 35.40 = 17.70 × 2.0.
  → the invariant holds at ENTRY.
- **46 of 92 post-policy CLOSED rows VIOLATE**, exit timestamps **2026-07-14T01:07Z → 2026-07-17T19:23Z**.
  The latest violation (19:23Z) is ~3h AFTER the running PID started (16:00Z) → **the running loop's code
  does NOT fix the invariant on the close path.**
- Two distinct subclasses:
  - **Subclass A — `allocated_margin_usd == 0` (20 rows).** Margin never set at all; invariant cannot hold.
    This is a SEPARATE, more basic write-path gap than the accumulation-freeze CG-F050 describes — flag to Codex.
  - **Subclass B — accumulation-freeze (26 rows).** margin>0 but notional grew via same-side fills while
    margin/leverage stayed frozen at initial. Ratio varies 2x–12x (not a fixed half-margin sizing bug):
    KITEUSDT 24.00 vs 6.00×2.0 (2x); MEGAUSDT 152.63 vs 22.18×2.0 (~3.4x); AGLDUSDT 107.16 vs 8.69×2.0 (~6x).
- **Mechanism confirmed**: invariant holds at entry, breaks by close specifically when realized size diverges
  from initial allocation via same-side accumulation — exactly CG-F050's claimed mechanism, STILL ACTIVE.
- **Verdict**: fix NOT effective on the running loop. Status stays PENDING. This is the recurring
  process-code-mismatch (running PID predates the fix, which is currently in Codex's uncommitted tree).

## CG-F049 (SHORT-edge sign inversion) — RUNTIME VALIDATION: **NEGATIVE (still pending)**
- Closed-trade L/S balance: **LONG 68 closes, net −$14.89 | SHORT 24 closes, net +$0.48**.
- **Book is 73.9% long (≈2.8:1)**, longs bleed while shorts PROFIT — the exact "shorts profit but are
  starved" signature CG-F049 predicted (claim said ~2.6:1). The corrected short-admission behavior
  (favorable shorts should now allocate and rebalance the book) is **NOT yet visible in runtime**.
- **Verdict**: fix NOT yet reflected in the running loop. Status stays PENDING.

## Consequence for the 6 red guardian gates (2026-07-18T01:04Z)
All are downstream of fixes NOT owned/activatable by me right now:
- **G10** = CG-F050 (write-path fix Codex-lane + historical repair operator-gated). Directly evidenced above.
- **G13 / G14** = CG-F052 stop-sizing (Codex sizing_model.py/exits.py, actively uncommitted) + genuine
  performance recovery. Book PF 0.658, notional-wtd −18.1bps.
- **G11** = counterfactual sweep FAILs because the book carries the G10 violations + negative edge (downstream).
- **G12** = 8 warnings incl. S17 = CG-F051 dead liquidation exit (Codex-lane); script is Codex-excluded.
- **G03** = CG-F049/F050 (validated negative above) + CG-F051/F052 (Codex-lane) + CG-F053 (trainer-lane).

## Unblock path (the concrete gating next step)
1. Codex COMMITS the F049/F050/F051/F052 fixes currently in its uncommitted tree (81 files).
2. Drain-safe restart of `ai-bot-v2-trade-management-paper-loop` so the running loop loads the fixes
   (operator action; paper loop only — the separate trading process stays untouched and BLOCKED).
3. Re-run THIS validation. Expect: new closed rows coherent (invariant holds through close), L/S balance
   rebalancing toward shorts, and the accumulation-freeze + allocated_margin==0 subclasses gone from NEW rows.
4. Historical 46 violating rows remain until the operator authorizes `tools/g10_capital_invariant_repair.py`
   (reversible margin-rebase, G08-safe) — the auto-mode classifier blocked the bulk Redis rewrite pending
   explicit operator authorization.

## Safety
Read-only. No writes to old keys, no order placement, no live enablement. Live gate BLOCKED throughout.

---

## Re-validation addendum — 2026-07-18T02:40Z (read-only, independent)

**Context change since the negative 2026-07-17 validation:** the paper loop was RESTARTED at
2026-07-18T02:25:27Z (new PID 2878). Both fix files (`position_state.py`, `sizing_model.py`)
have mtime 2026-07-18T00:52Z — i.e. the running process now includes the fix code, which the
previous negative validation identified as the missing precondition (old PID 2215061 predated
the fix load).

**CG-F050 (capital invariant):**
- Open positions (2): MANAUSDT gross 76.22 = 38.11×2.0; ARBUSDT gross 35.40 = 17.70×2.0 —
  both COHERENT (use `net_quantity` for open rows; `closed_quantity` only exists on closed rows).
- Rows exited after 2026-07-17T20:00Z: 1/1 PASSES the invariant (tol $0.02). First
  post-fix-era close to hold.
- Verdict: EARLY-POSITIVE but INSUFFICIENT SAMPLE (n=1; and rows must both OPEN and CLOSE
  under the fixed code, incl. same-side accumulation, for a clean test). Status remains
  FIX_APPLIED_PENDING_INDEPENDENT_RUNTIME_VALIDATION. Re-validate after ≥10 closes with
  entry ts > 2026-07-18T02:25Z; specifically require ≥1 multi-fill (accumulated) close to
  test the apply_same_side_fill recompute path.
- The 46 pre-fix violation rows are historical failed evidence (per master-doc addendum),
  not rows to rewrite; G10 will keep failing on them until the gate scopes to post-fix entries.

**CG-F049 (short admission):**
- Last 12h closes: 7, ALL LONG (net −$4.35), 0 SHORT. Both open positions LONG (opened
  pre-restart). Corrected short admission CANNOT yet be observed — no post-restart
  admissions have occurred in the 15 minutes since PID 2878 started.
- Verdict: NOT YET OBSERVABLE post-restart; remains PENDING. Signature to look for:
  favorable-edge shorts admitted with non-zero risk budget and leverage >1x.

Validator: Claude (read-only; no trading-flow code touched). Method: direct Redis reads
(`v2:paper:positions`, `v2:paper:closed_trades`), process table, file mtimes.

---

## Refresh — 2026-07-18T22:14Z (re-observation, read-only)

Re-ran the observation to check whether the WQ-R34 external dependencies moved. They have not.

- **Codex F049/F050 fixes STILL UNCOMMITTED.** `git status` shows 12 dirty files in the Codex
  lane (`v2/backend/app/services/adaptive_capital_allocator/` + `.../paper_trade_management/`).
  The running loop therefore still cannot carry the fix even if restarted.
- **Paper-loop service is currently DEAD.** `ai-bot-v2-trade-management-paper-loop.service` =
  `inactive (dead) since 2026-07-18 18:12:37 EDT` (Main PID 1641118 exited status 0/SUCCESS, clean).
  While dead, no new closed outcomes accumulate, so G10/G13/G14 cannot advance regardless.
- **Guardian gates unchanged** vs prior tick: G10 = 46 capital-invariant violations (20 subclass-A
  allocated_margin==0, 26 subclass-B accumulation-freeze); G11 sweep FAIL; G12 8 warns; G13 −18.13 bps;
  G14 PF 0.658. G01/G02/G04–G09/G15/G16 PASS.

### Conclusion (unchanged): WQ-R34 remains BLOCKED_EXTERNAL_DEPENDENCY
My Claude-lane part (independent runtime validation) is complete and negative. The unblock path is
entirely outside my lane and must not be performed by me:
1. **Codex** commits the F049/F050/F051/F052 fixes (currently uncommitted).
2. **Operator** drain-safe restart of the paper loop (paper-only; trading stays BLOCKED). It is
   currently stopped — an operator restart with the committed fix is the gating event.
3. **Claude** re-runs this validation (expect new coherent closes + L/S rebalance).
4. **Operator** authorizes `tools/g10_capital_invariant_repair.py` for the 46 historical rows
   (reversible, G08-safe; the auto-classifier blocked the bulk rewrite by design).

No further Claude action is available until steps 1–2 occur. This refresh is evidence-integrity
documentation only; no code, no Redis writes, no process changes, live gate BLOCKED.

---

## Re-validation — 2026-07-20T06:40Z (read-only, independent)

**Both prior gating preconditions have now occurred:**
1. Codex COMMITTED paper-lane fixes: ed115ac695 "make leverage continuous and side-aware"
   (2026-07-18 14:18 EDT), b20c5afa7f, 57dfaa9df9 "enforce canonical writer ownership"
   (2026-07-18 20:39 EDT), and later f8a1349061 "enforce earned leverage envelope"
   (2026-07-19 04:59 EDT).
2. Paper loop RESTARTED: **PID 1816509, started 2026-07-18 20:45:20 EDT (2026-07-19T00:45:20Z)**
   — 6 minutes after 57dfaa9df9. Running ~30h at validation time. Note: the running process
   PREDATES f8a1349061 by ~8h and the file remains dirty in Codex's tree (the recurring
   process-code-mismatch persists for the newest fix).

**Result: VALIDATION CANNOT CONCLUDE — the restarted loop has admitted NOTHING in 30h.**
Method: same read-only invariant + L/S check (`v2:paper:closed_trades`, `v2:paper:positions`,
both now JSON-string blobs) filtered to exits > 2026-07-19T00:45:20Z.

- Closes after PID start: **0 of 92** (newest close remains 2026-07-17T22:48Z, pre-restart).
- Open positions: **0**.
- `v2:paper:trade_management:status` (stamped fresh every 60s cycle, 2026-07-20T06:35Z):
  `intents_built: 0`, `candidate_count: 0`, `strategy_supply_sourced_count: 0`,
  `accepted_count: 0`, `blocked_count: 0`, ALL rejection/block reason maps EMPTY.
  This is not gate-blocking — **zero candidates reach the funnel at all**.
- Upstream supply is FRESH at the same moment: `v2:strategy_supply:gate_clean_positive_hypotheses:*`
  age ~20s (33 keys), `v2:opportunity:*` age ~124s (5 keys),
  ai-bot-v2-orchestrator-arbitration-loop + a-plus-context + alt-data publisher all active.
- Signal-consumption regression across the restart: prior PIDs logged
  `DEBUG: Processing signal N/593` every cycle (stdout log, last written 2026-07-18 00:38 EDT);
  the current PID has written **zero bytes** of signal-processing output in 30h
  (process stdout confirmed bound to that log via /proc/1816509/fd/1).
  **593 signals/cycle → 0 signals/cycle across the restart while supply stayed fresh.**
- Historical note (not current): 94 `UnboundLocalError: local variable 'json'`
  (v2_trade_management_paper_loop.py:30761, run_once) crashes in the .err log, last written
  2026-07-16 15:14 EDT — an earlier crash-loop cause, apparently resolved before this PID.

**NEW BLOCKING SUB-DEFECT (Codex-lane): signal intake severed in the restarted code state.**
The loop cycles healthily (fresh status stamps, PASS writer-ownership validation, margin PASS)
but consumes no signals, so no new closes can EVER accumulate to validate CG-F049/F050 —
and G04-lane sample growth, G13/G14 recovery, and 1000x progress are all frozen with it.
Most likely introduced between the pre-restart code state and the 2026-07-18 20:45 restart
cohort (ed115ac695 / b20c5afa7f / 57dfaa9df9 or the then-dirty tree); the canonical-writer
enforcement in 57dfaa9df9 is the natural first suspect for over-fencing the signal source read.

### Verdict
- CG-F050: **STILL PENDING** — 0 new closes to test (prior early-positive n=1 unchanged).
- CG-F049: **STILL PENDING** — 0 new admissions; L/S rebalance unobservable.
- WQ-R34: remains **BLOCKED_EXTERNAL_DEPENDENCY**, but the blocker has CHANGED:
  it is no longer "PID predates fix" — it is (a) zero-candidate starvation in the running
  loop (Codex must diagnose/fix the signal intake in v2_trade_management_paper_loop.py,
  their actively-dirty file), then (b) another drain-safe restart that also picks up
  f8a1349061, then (c) re-run this validation after ≥10 post-restart closes incl. ≥1
  multi-fill accumulation close.

Validator: Claude (read-only; no trading-flow code touched; live gate BLOCKED throughout).
