# 121 Missing Evidence Gaps

The 2F.B assembler evidence is reconciled and READY, but full pre-live runtime evidence is not complete.

## Gaps To Preserve

- `signal_id`: Evidence missing — cannot explain without guessing.
- `risk_decision_id`: Evidence missing — cannot explain without guessing.
- `execution_intent_id`: Evidence missing — cannot explain without guessing.
- `paper/shadow/live-blocked result`: Evidence missing — cannot explain without guessing.
- `audit ledger event`: Evidence missing — cannot explain without guessing.
- `dashboard-visible end-to-end chain`: payload requirement exists, full runtime/UI proof remains follow-up.

## Boundary

The orchestrator may propose, coordinate, enrich, rank, and deconflict. It must not be represented as final execution authority. The Risk Gateway remains final authority before execution. Trader/execution acts only on an approved execution intent.

## Safety

Do not hide these gaps behind natural-language summaries. Any UI panel that lacks raw evidence must show the missing-evidence text above.
