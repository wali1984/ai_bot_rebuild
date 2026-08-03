# ATR-Stop Ceiling (CG-F052) — IMPLEMENTED, env-gated OFF, AWAITING OPERATOR ACTIVATION

Date: 2026-07-17
Commit: 7b0f1ebb65 (isolated: exits.py + test_phase7_hedge_and_exits.py only)
Finding: CG-F052 (critical) — negative edge is the exit ladder, not prediction

## What shipped (inert until activated)
New `TIER_1_ATR_CEILING_STOP` exit tier in exits.py that cuts a loser at
`atr_stop_ceiling_bps` BEFORE the -150bps catastrophic floor. It does NOT modify
`effective_atr_stop_bps` (which the allocator also uses for sizing), so position
sizing is unchanged — only realized loss magnitude shrinks. Fires only when a
symbol's own tighter ATR stop did not already trigger, so low-ATR positions still
exit at their own stop; winners exit via trailing well before any ceiling.

Default `atr_stop_ceiling_bps=0` = DISABLED = current behavior. Activated only by
setting env `PAPER_ATR_STOP_CEILING_BPS`. 4 isolated tests; 381 ptm tests pass.

## Expected result (counterfactual over the live 90-trade session)
| ceiling | book net | PF | losers capped | winners cut |
|--------:|---------:|-----:|--------------:|:-----------:|
| off (actual) | -$7.93 | 0.816 | — | — |
| -60 bps | +$10.53 | 1.645 | 25 | 0 |
| -80 bps | +$6.81 | 1.339 | 22 | 0 |
| -100 bps | +$3.53 | 1.151 | 21 | 0 |
| -120 bps | +$0.27 | 1.010 | 21 | 0 |

**CORRECTION (2026-07-17 19:52, adversarial edge-decomposition wl9km4uih):** the table
above is SURVIVORSHIP-OPTIMISTIC and must NOT be used. It relabels realized closed
outcomes as if the stop had perfect foresight (cut exactly the losers, never a winner).
A REAL intra-trade stop fires when adverse excursion TOUCHES -80bps *during* the trade,
which also whipsaws ~4-7 dip-and-recover names — including **4 realized winners** — that
dipped below -80 intra-trade and recovered. My earlier "zero false cuts" check was wrong:
it only examined CLOSED losers (which didn't recover), not the intra-trade excursions of
winners. Honest, independently re-verified numbers:

| fix | book net | PF |
|-----|---------:|----|
| actual | -$11.89 | 0.68 |
| honest intra-trade -80bps ceiling | **~-$2.49** | 0.90 |
| + fix 3 blown-through stops | ~-$1.85 | 0.92 |

The ceiling is still the **single biggest lever** and worth activating — it HALVES the
loss and bounds catastrophic tail risk (CLAUDE.md survival/liquidation priorities). But
it does **NOT** flip the book positive and it **does** whipsaw ~4 winners; accept that as
the deliberate cost of bounding tail risk. Do NOT sum per-dimension counterfactuals
(+$6.81 ceiling + short + stale ≈ +$20 triple-counts the same ~34 catastrophic-floor
longs). **The book cannot reach positive expectancy by risk-mgmt fixes alone — the model
has no demonstrable directional edge (see CG-F053); that is the true 1000x binding
constraint and is a TRAINER problem.** Recommended value still -80bps.

## TO ACTIVATE (operator — this is a RISK change + a paper-loop restart)
    cat > ~/.config/systemd/user/ai-bot-v2-trade-management-paper-loop.service.d/60-atr-stop-ceiling.conf <<'CONF'
    [Service]
    Environment=PAPER_ATR_STOP_CEILING_BPS=80
    CONF
    systemctl --user daemon-reload
    systemctl --user restart ai-bot-v2-trade-management-paper-loop.service

Verify after restart: new closed losers should show close_reason
`TIER_1_ATR_CEILING_STOP` at ~-80bps instead of `TIER_0_CATASTROPHIC_FLOOR_STOP`
at -150bps; G13/G14 recover as the -80bps-capped cohort replaces the -150bps one.

## TO ROLL BACK
    rm ~/.config/systemd/user/ai-bot-v2-trade-management-paper-loop.service.d/60-atr-stop-ceiling.conf
    systemctl --user daemon-reload && systemctl --user restart ai-bot-v2-trade-management-paper-loop.service

## Why NOT auto-activated
Stop levels are a risk setting — the mandatory change protocol requires operator
approval for risk changes, and activation restarts the live paper loop. The drop-in
is deliberately NOT written to the live systemd dir so a self-healing-supervisor
restart cannot silently enable it. LIVE trading stays BLOCKED regardless.

## Still Codex-lane (not this change)
- The 3 blown-through-tight-stop rows (AGLDx2, FET: 68bps stop -> -180bps) are a
  stop-ENFORCEMENT failure (CG-F043 recurrence), separate from the ceiling.
- CG-F051 inert liquidation exit (exits.py:356 reads nonexistent attribute).
- CG-F049 short-edge inversion (favorable shorts blocked -> book 2.6:1 long; shorts
  +7.4bps vs longs -16.5bps).
