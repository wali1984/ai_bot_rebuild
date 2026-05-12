# Validation Commands

```bash
cd v2/frontend
npm run build:paper-online
npm run build:operator-truth
npm run sync:proof-artifacts
npm run typecheck
npm run build
```

Git snapshot at generation:

- git status: `M .gitignore
 M v2/frontend/package.json
 M v2/frontend/scripts/build-operator-truth-payload.mjs
 M v2/frontend/src/pages/mission-control/index.tsx
 M v2/frontend/src/pages/operatorTruthComponents.tsx
 M v2/frontend/src/pages/operatorTruthData.ts
 M v2/frontend/src/pages/paper-trading/index.tsx
?? claude_worklog/final_readiness/v2_paper_online_operational_recovery/
?? v2/backend/app/cli/paper_online_runtime.py`
- git head: `ddb6700 Refresh operator truth payload after production crawl`
