OPERATOR_UI_HARD_FAIL_DESIGN_TO_CODE_AND_RUNTIME_TRUTH_RECOVERY_REPORT

Result: READY.

What changed:
- Mission Control now renders a first-screen `Mission Control Truth Deck`.
- The truth deck makes live gate, supervisor stale/conflict state, trainer runtime missing state, legacy orchestrator observation, signal lineage fixture status, stale payload count, and missing evidence count visible immediately.
- Monitor Center, Trainer Prediction Monitor, and Signal Explainability now include route-level truth summaries.
- Detailed payload freshness and raw process evidence are still available, but moved behind explicit detail affordances where appropriate.
- The market/chart/proof section is now labeled as proof context below the truth deck.

Current runtime truth:
- Supervisor: `SUPERVISOR_STATUS_STALE_OR_CONFLICTING`
- Trainer: `TRAINER_RUNTIME_EVIDENCE_MISSING`
- Signal lineage: `STATIC_PROOF_FIXTURE`
- Redis trim: deferred/non-blocking
- Live trading: `blocked_human_only`

Validation evidence:
- Browser screenshots captured before and after implementation.
- TypeScript typecheck passed during implementation.
- Final validation artifacts are recorded in this packet.

Scope boundary:
- This was frontend truth-surface recovery and proof synchronization only.
- No legacy bot mutation occurred.
- No Redis write or trim occurred.
- No exchange action occurred.
- No live mode, leverage, margin, or key activation occurred.
