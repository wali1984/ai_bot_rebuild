OPERATOR_UI_HARD_FAIL_RECOVERY_REPORT

Result: READY.

Implemented:
- Grouped, styled admin navigation with active route highlighting and warning counts.
- Mission Control first screen rebuilt around runtime truth, not raw proof payloads.
- Critical system cards for paper/shadow, trainer, orchestrator, risk gateway, execution, Redis/V2 data plane, Postgres/audit ledger, and live block.
- Compact signal stream table with signal/prediction IDs, confidence, freshness, risk result, and flags.
- Paper Trading, Replay, and Live Readiness placeholder shells replaced with useful non-live evidence pages.
- Route truth summaries added to key secondary pages.
- TradingView widget now shows loading/fallback state instead of silently rendering a blank black panel.
- Browser screenshot acceptance artifacts added.

Current truth status:
- Supervisor: `SUPERVISOR_STATUS_STALE_OR_CONFLICTING`
- Trainer monitor: `TRAINER_RUNTIME_EVIDENCE_MISSING`
- Signal lineage: `STATIC_PROOF_FIXTURE`
- Redis trim: deferred/non-blocking
- Live gate: `blocked_human_only`

Validation:
- `npm run build:operator-truth`
- JSON validation
- `npm run sync:proof-artifacts`
- `npm run typecheck`
- `npm run build`
- Playwright/Chromium route smoke and screenshots
- High-confidence secret scan
- Safety scan
- Redis trim approval absence check
- `git diff --check`

No forbidden action occurred:
- Legacy bot was not modified.
- Redis was not written.
- Redis trim approval file was not created.
- No exchange order/cancel/leverage/margin/live action occurred.
