# V2 Current Paper Fill Gate Acceptance Recovery Report

Gate: `V2_CURRENT_PAPER_FILL_GATE_ACCEPTANCE_RECOVERY_READY`
Generated EST: `2026-06-09T15:07:21-04:00`
Accepted fills after repair: `6`
Held rows after repair: `116`
Valid blocks: `116`
Bug blocks: `0`
Over-strict blocks: `0`
Paper equity: `10000.0`
Primary reason: `PAPER_FILLS_ACCEPTED_FROM_CURRENT_DECISIONS`

Current held decisions remain blocked because current evidence does not pass paper-fill criteria. No old June 5 fills were copied into the current ledger.

Safety: no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, no raw credential output.
