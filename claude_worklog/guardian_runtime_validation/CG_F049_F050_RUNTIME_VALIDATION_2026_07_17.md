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
