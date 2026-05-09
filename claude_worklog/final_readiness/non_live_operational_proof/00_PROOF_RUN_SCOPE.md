# Non-Live Operational Proof Run

## Objective

Collect evidence that V2 non-live replay/backtest, paper mode, and shadow-readiness surfaces are usable.

## Hard safety

This proof run must not:
- modify /home/wali/Desktop/AI BOT
- write Redis
- delete Redis keys
- restart live services
- place/cancel orders
- change leverage/margin
- enable live trading
- deploy
- expose secrets

## Expected outcome

Evidence for:
- replay/backtest runner
- paper mode
- shadow readiness
- risk gateway default-deny behavior
- paper ledger
- explainability lineage
- live gate blocked

NON_LIVE_OPERATIONAL_PROOF_SCOPE_READY
