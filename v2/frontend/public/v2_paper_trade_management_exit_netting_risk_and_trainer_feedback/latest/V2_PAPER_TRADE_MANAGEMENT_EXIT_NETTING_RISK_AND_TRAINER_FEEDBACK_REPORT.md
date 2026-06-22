# V2 Paper Trade Management Exit Netting Risk And Trainer Feedback Report

Generated: `2026-06-11T20:27:36Z`

Verdict:

```text
V2_PAPER_TRADE_MANAGEMENT_EXIT_NETTING_RISK_AND_TRAINER_FEEDBACK_READY
```

Implemented paper-first controls:

- Same-symbol same-side fills net into one paper position.
- Same-symbol opposite-side fills reduce or close before any reverse exposure.
- Symbol and total exposure controls use percentage-based operator envelopes, not fixed runtime 200 USDT sizing.
- Stop loss, take profit, trailing stop, max-hold timer, model reversal netting, and emergency liquidation-distance close paths are present.
- Close/reduce produces realized PnL, fees, slippage, hold time, close reason, winner flag, and closed-trade outcome labels.
- Trainer loader consumes `v2:paper:outcome_labels` and `v2:trainer:feedback:outcomes` before fallback labels.
- Risk gateway calls the V2 evaluator set before returning allow.
- Shared lifecycle guard blocks missing lineage, invalid market state, invalid risk decisions, caps, netting violations, drawdown guard, kill switch, halt, and reduce-only entry attempts.

Adaptive sizing review:

- Current paper runtime and live pre-submit paths use `V2_ADAPTIVE_AI_CAPITAL_ALLOCATOR`.
- No current paper trade-management or live pre-submit runtime path uses a fixed 200 USDT target or cap.
- Remaining fixed numeric hits are tests, HTTP status codes, basis-point thresholds, row limits, compatibility fields, old operator packets, or live canary code intentionally left untouched without live execution approval.

Validation:

- `py_compile`: PASS.
- Focused backend tests: PASS, 137 passed.
- Paper loop one-shot: PASS, `V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK`.
- Static sizing scan: PASS for current runtime with legacy packet/canary caveats.
- Old Redis scan: PASS, touched paper runtime writes are `v2:` only.
- Exchange mutation scan: PASS for validation, no real orders/test-order/cancel/modify/leverage/margin mutation.
- Raw secret scan: PASS, no raw credential payload exposure in changed runtime path.

Remaining live boundary:

- Live code remains balance/margin-held. This pass does not authorize live order submission and does not modify leverage or margin mode.

