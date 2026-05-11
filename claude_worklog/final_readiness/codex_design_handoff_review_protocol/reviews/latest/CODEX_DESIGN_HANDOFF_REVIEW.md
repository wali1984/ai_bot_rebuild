# Codex Design Handoff Review

Status: `CODEX_DESIGN_HANDOFF_REVIEW_FAIL`

FAIL. Main routing and TradingView primary chart are partially correct, but the handoff cannot pass the required policy.

Key blockers:
- `LiveBlockBanner` can render `PENDING APPROVAL` and green `ACTIVE (bounded)` states from `/api/v1/risk/live-readiness` instead of always preserving global `LIVE TRADING: BLOCKED_HUMAN_ONLY`.
- Monitor Center only renders `payload.monitors` from the cockpit payload; System Atlas reports 253 monitor scripts and 4194 scripts, so all monitors and trainer prediction stream are not shown.
- Trainer Prediction Monitor and Signal Explainability reuse static cockpit decision rows instead of dedicated trainer/signal lineage evidence, and do not label every explained value with source/freshness truth.
- Generic `PageShell` placeholder routes use a broad evidence-gap sentence without exact missing source, expected payload, or follow-up task.
- Config Admin renders only four cockpit settings and does not classify every required dangerous setting in the runtime table.
- Read-only market payload top-level feed says fresh while candle rows show stale; chart labeling does not expose row-level stale freshness.
- System Atlas remains blocked with unmapped exchange action paths, Redis writer paths, runtime processes, and unsafe unknown files.

Positive checks:
- `/` and `/admin` redirect to `/admin/mission-control?role=admin`.
- Required routes remain registered.
- TradingView is the normal chart widget; SVG candles are fallback-only.
- The chart has `READONLY_MARKET_FEED` / `STATIC_PROOF_FIXTURE` label text.
- No direct import of handoff `data.jsx` was found in `v2/frontend/src`.
- No frontend code reviewed directly places orders, mutates Redis, changes leverage/margin/position mode, or enables live trading.

Required before PASS:
1. Force the global banner to remain blocked/human-only in this scope.
2. Wire Monitor Center to complete monitor/script registry/runtime evidence.
3. Add dedicated Trainer Prediction Monitor payload and labels.
4. Add dedicated Signal Explainability evidence or exact `MISSING_EVIDENCE` gaps.
5. Replace generic route gaps with per-route source/payload/task details.
6. Expand Config Admin classifications for all required dangerous settings.
7. Surface stale market/candle freshness near chart values.

Safety statement: review-only except writing the two required review artifacts under the allowed prefix. No legacy bot changes, Redis mutation, Redis trim approval file, service restart, exchange action, leverage/margin/position-mode change, live enablement, or secret exposure was performed.
