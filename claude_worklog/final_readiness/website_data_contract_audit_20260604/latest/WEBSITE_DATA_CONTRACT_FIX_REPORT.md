# Website Data Contract Fix Report

Generated EST: `2026-06-04`

Scope: frontend data-contract repair without redesign/layout ownership changes.

## Fixed

- Removed default dashboard call to missing backend endpoint `/api/v1/live-readiness/banner`; it is now opt-in via `VITE_ENABLE_ONLINE_READINESS_BANNER_API=true`.
- Replaced missing queue API dependency `/api/v1/_meta/queue-status` with current public static evidence `/v2_closed_loop_execution/latest/task_lifecycle_status.json`, with backend API opt-in via `VITE_ENABLE_QUEUE_STATUS_API=true`.
- Corrected paper runtime payload path from missing `/operator_runtime/paper_online/latest/paper_online_status.json` to existing `/operator_runtime/paper_online/latest/paper_runtime_status.json`.
- Corrected Audit Ledger operator review path from missing `/operator_runtime/v2_operator_review/latest/v2_operator_review.json` to existing `/operator_runtime/v2_operator_review/latest/v2_operator_review_status.json`.
- Expanded `usePayloadFile` freshness parsing beyond `generated_at` and `generated_utc` to include `generated_est`, `timestamp`, `received_at`, `heartbeat_at`, `last_run_ts`, `finished_at`, `updated_at`, and `freshness.runtime_age_seconds`.
- Reduced false “broken data” noise on Research by rendering optional unavailable provider scores as `not available` while keeping provider flags visible.

## Validation

- `npm run typecheck` passed.
- `npm run build` passed.
- Route crawl: `44` canonical routes.
- Failed requests after fixes: `0`.
- Page errors after fixes: `0`.

Evidence files:

- `route_data_contract_crawl.json` before fixes.
- `route_data_contract_crawl_after_fixes.json` after hard 404 fixes.
- `route_data_contract_crawl_final_after_queue.json` after queue remap.

## Remaining Real Reasons

- `/market/BTCUSDT`: remaining markers are provider/status fields such as `KEY_MISSING_NO_NETWORK`, `MISSING_PROVIDER_DATA`, and stale-provider flags emitted by current payloads. These require provider credentials, paid-tier access, or fresh upstream provider output; the frontend cannot fabricate them.
- `/system/evidence` and `/system/reports`: these pages intentionally render historical/static proof and report-lane freshness. Stale/missing markers here are evidence state, not current runtime truth.
- `/dashboard`: remaining blockers come from live readiness and migration truth payloads: native-core gaps, expected-move review gaps, and live gate blockers.
- `/markets`, `/trade`, `/derivatives`, `/signals`, `/ai-predictions`, `/backtests`, `/system/trainer`, and `/system/readiness`: remaining missing markers are current paper/risk/model readiness gaps or disabled live/canary controls without backend approval/audit endpoints.

Safety state unchanged: no live/canary enablement, no order/test-order/cancel/modify, no leverage/margin mutation, no old Redis write, no legacy restart, no Redis trim.
