# V2 Paper Edge Recovery And Cost-Aware Trade Selection Report

Generated: `2026-05-15T09:00:09Z`
Task: `claude_v2_paper_edge_recovery_and_cost_aware_trade_selection`

## Decision

`V2_PAPER_EDGE_RECOVERY_READY_NO_UNSAFE_FILLS_EDGE_PENDING`

This does not approve live, canary, or legacy shutdown. Positive paper edge remains unproven.

## What Changed

- The strict cost-aware paper gate remains active.
- The temporary fee-bleed guard was replaced with a non-live paper position lifecycle.
- The lifecycle can open paper-only positions, hold them across ticks, and close on take-profit, stop-loss, or max-hold timeout.
- Runtime events now include `paper_outcome_model_status=READY`.

## Runtime Verification

After restarting only `ai-bot-v2-paper-online-runtime.service` at `2026-05-15T08:47:22Z`:

| Metric | Value |
| --- | ---: |
| observed events | 26 |
| fills | 0 |
| held positions | 0 |
| closed positions | 0 |
| blocked intents | 26 |
| fees charged | 0.0 |
| latest paper PnL | -49.15 |

The first post-lifecycle ticks were blocked because confidence and/or edge-after-cost were below threshold. Latest observed event: `2026-05-15T08:59:56Z`, blocked by `deny_low_confidence` with `confidence=0.560401`. That is correct behavior: no edge means no fill.

## Fill Boundary

A V2 paper fill is blocked unless all of these pass:

- `expected_move_after_cost_bps >= 8`
- `confidence_calibrated >= 0.70`
- accepted trainer source
- current feature freshness
- paper symbol eligibility
- `live_gate == blocked_human_only`
- `live_symbols == []`
- cooldown / flip / churn clear
- risk gateway allows paper
- non-live paper position lifecycle is ready

## Remaining Work

- Keep collecting paper/shadow observations until there is enough post-lifecycle sample evidence.
- Do not claim positive edge with zero qualifying fills.
- Trainer derived/native evidence and trade-permission classification remain unresolved.

## Validation

- `py_compile`: PASS for `v2/backend/app/cli/paper_online_runtime.py`.
- Focused tests: `20 passed`.
- Runtime safety: old Redis writes absent, exchange actions absent, top-level `live_gate=blocked_human_only`, top-level `live_symbols=[]`.
