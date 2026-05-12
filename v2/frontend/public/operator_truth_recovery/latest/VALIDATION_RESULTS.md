# Validation Results

Commands run:

- `cd v2/frontend && npm run build:operator-truth` — passed.
- JSON validation for generated operator truth artifacts — passed.
- `cd v2/frontend && npm run sync:proof-artifacts` — passed.
- `cd v2/frontend && npm run typecheck` — passed.
- `cd v2/frontend && npm run build` — passed.
- Playwright/Chromium smoke for `/`, `/admin/mission-control?role=admin`, `/admin/monitor-center?role=admin`, `/admin/trainer-prediction-monitor?role=admin`, `/admin/signal-explainability?role=admin`, `/admin/build-validation-status?role=admin`, and `/admin/operator-proof-dashboard?role=admin` — passed.
- Root render check waited for `operator-truth-status-strip` and confirmed `TRAINER_RUNTIME_EVIDENCE_MISSING` plus `SUPERVISOR_STATUS_STALE_OR_CONFLICTING` are visible.
- `git diff --check` — passed.
- high-confidence secret scan — clean.
- safety scan for live/exchange/capital/Redis mutation strings in modified sources — clean.
- Redis trim approval absence check — `REDIS_TRIM_APPROVAL_ABSENT_OK`.

Render proof:

```json
{
  "root_final_url": "http://127.0.0.1:5173/admin/mission-control?role=admin",
  "truthStripVisible": true,
  "legacyRuntimeVisible": true,
  "trainerPreviewVisible": true,
  "signalPreviewVisible": true,
  "payloadFreshnessVisible": true,
  "liveBannerVisible": true,
  "trainerMissingVisible": true,
  "supervisorConflictVisible": true
}
```
