# Website Readiness Audit - Non-Live Operator Dashboard

## Result

The browser-facing V2 frontend exists under `v2/frontend`, but before this
audit it did not expose a dedicated read-only operator dashboard for the latest
non-live proof harness artifacts.

## Implemented Dashboard

Added a local-only read-only admin page:

```text
/admin/operator-proof-dashboard
```

The page reads static proof artifacts copied into:

```text
v2/frontend/public/non_live_operational_proof/latest/
```

Displayed evidence includes:

- GO/NO-GO state
- live gate status
- replay/backtest scenario counts
- risk gateway block decisions
- paper ledger open/close/reduce/block events
- shadow legacy-vs-V2 comparison
- LAB hedge unwind explanation
- aggregate proof rollup

## Local Run Command

```bash
cd "$HOME/Desktop/AI BOT REBUILD/v2/frontend"
npm install
npm run dev -- --host 127.0.0.1
```

Open:

```text
http://127.0.0.1:5173/admin/operator-proof-dashboard?role=admin
```

## Safety

The dashboard is read-only and uses static files served by Vite. It does not:

- write Redis
- mutate the legacy bot directory
- restart trading services
- place or cancel orders
- change leverage or margin
- enable live mode
- deploy externally

## Validation

- `npm run typecheck`
- `npm run build`
- targeted Playwright smoke test for `/admin/operator-proof-dashboard`
- Chromium render check confirmed:
  - `NON_LIVE_OPERATOR_PROOF_HARNESS_READY`
  - `blocked_human_only`
  - risk blocks section
  - paper ledger section
  - shadow comparison section
  - decision explainability section

## Marker

WEBSITE_READINESS_OPERATOR_DASHBOARD_READY
