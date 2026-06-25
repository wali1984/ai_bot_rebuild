# Website Lane Contract

Generated: 2026-06-23

This contract defines the Codex-owned trader website lane for the NERVYX ONE final trader-account and trader-facing surface work.

## Scope

Codex owns only trader-facing, authenticated, read-only website projection work and the evidence needed to verify it.

Owned areas:

- `backend/app/api/v2` read-only trader, account, and market adapters
- backend tests for those adapters
- `frontend/src/api`
- `frontend/src/hooks`
- `frontend/src/stores`
- `frontend/src/selectors`
- `frontend/src/types`
- `frontend/src/data`
- `frontend/src/components/trade`
- `frontend/src/components/trading`
- `frontend/src/components/charts`
- `frontend/src/components/data`
- `frontend/src/pages/dashboard`
- `frontend/src/pages/account-settings`
- `frontend/src/pages/portfolio`
- `frontend/src/pages/positions`
- `frontend/src/pages/executions`
- `frontend/src/pages/history`
- `frontend/src/pages/markets`
- `frontend/src/pages/market`
- `frontend/src/pages/trader`
- `frontend/src/pages/derivatives`
- `frontend/src/pages/signals`
- `frontend/src/pages/ai-predictions`
- `frontend/src/pages/backtests`
- `frontend/src/pages/research`
- `frontend/src/pages/alerts`
- trader-focused tests and release evidence

## Non-Owned Areas

Codex must not edit these files or route families in this lane:

- `frontend/src/router.tsx`
- `frontend/src/pages/productNavigation.ts`
- `frontend/src/styles/tokens.css`
- `frontend/src/styles/layout.css`
- `frontend/src/styles/admin.css`
- `frontend/src/pages/admin*`
- `frontend/src/pages/mission-control`
- `frontend/src/pages/monitor-center`
- `frontend/src/pages/system-health`
- `frontend/src/pages/ingestors`
- `frontend/src/pages/trainer-admin`
- `frontend/src/pages/orchestrator-admin`
- `frontend/src/pages/execution-admin`
- `frontend/src/pages/exchange-manager`
- `frontend/src/pages/config*`
- `frontend/src/pages/report-center`
- `frontend/src/pages/logs-errors`
- `frontend/src/pages/audit-ledger`

Claude owns those areas.

## Styling Boundary

Trader-specific styling may be created only in:

- `frontend/src/styles/trader.css`
- `frontend/src/components/**/[component].module.css`
- `frontend/src/pages/**/[page].css`

Do not modify global layout, token, or admin styles in this lane.

## Live Execution Boundary

Real live execution remains blocked. This lane may not change:

- PPO logic
- MASA logic
- trainer calculations
- strategy selection
- signal-generation semantics
- risk formulas
- execution routing
- exchange mutation
- Redis producer contracts
- live-gate transitions
- database trading records

Backend work is limited to authenticated, read-only projection and realtime delivery. No frontend-supplied trader ID may be accepted as authority.

## Audit And Evidence Order

1. Production trader baseline audit against `https://dashboard.wajidali.us` using real backend login.
2. Canonical field registry and data contract.
3. Auth-scoped trader read model and health endpoint.
4. One realtime trader store and canonical selectors.
5. Cross-page consistency test against the deployed domain.
6. Trader account surfaces.
7. Remaining trader pages in the requested order.
8. Final production release gate.

Frontend and backend source must not be modified before the production baseline artifact exists. If the real credentials are unavailable, the audit is `BLOCKED`, not bypassed with mocked auth or `?role=`.

## Required Status Terms

Defect statuses are:

- `OPEN`
- `IMPLEMENTED`
- `VERIFIED`
- `BLOCKED`

Do not use `DONE` or `FIXED` for implementation-only work.

## Verification Bar

A defect can be marked `VERIFIED` only when all six evidence items exist:

1. Source code fix.
2. Unit or contract test.
3. Deployed-domain screenshot before and after.
4. Rendered value compared with raw API or WebSocket value.
5. Cross-page comparison passed.
6. No console or network error.

The lane is complete only when the generated release gate allows `release_gate_pass: true`. Passing builds, loaded routes, open WebSockets, renamed loading text, or screenshots without overflow are not sufficient.
