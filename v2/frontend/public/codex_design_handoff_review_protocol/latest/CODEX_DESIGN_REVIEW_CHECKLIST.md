# Codex Design Review Checklist

Codex must mark each item PASS, FAIL, or WARN with raw evidence pointers.

## Design Handoff Completeness

- Latest handoff folder exists under `claude_worklog/frontend_design/handoffs/`.
- Design handoff protocol maps prototype files to V2 routes/components/payloads.
- Missing maps are reported as blockers or explicit evidence gaps.
- Claude Design output is treated as reference, not runtime truth.

## Route And Surface Review

- `/` and `/admin/mission-control?role=admin` show the intended enterprise cockpit.
- `/admin/operator-proof-dashboard?role=admin` remains evidence/proof-only.
- Mission Control remains the main cockpit.
- Monitor Center, Trainer Prediction Monitor, Signal Explainability, Config Admin, Script Registry, Exchange Manager, External / Manual Position Quarantine, Build Validation, and Mobile/iPhone readiness remain route-visible.

## Data Truth Review

- Mock design data is removed or labeled `DESIGN_MOCK_DATA_TO_REMOVE`.
- Static proof fixtures are labeled `STATIC_PROOF_FIXTURE`.
- Read-only market data is labeled `READONLY_MARKET_FEED`.
- Read-only account data is labeled `READONLY_ACCOUNT_FEED`.
- Runtime monitor data is labeled `RUNTIME_MONITOR_PAYLOAD`.
- Missing evidence uses explicit missing-evidence text and does not guess.

## Chart Review

- TradingView or approved lightweight chart is primary.
- Old SVG/static chart is fallback-only and explicitly labeled.
- Charts show source and freshness.

## Safety Review

- Global live-block banner remains visible.
- Admin AI cannot enable live trading or dangerous settings.
- Config Admin classifies dangerous settings and requires explicit approval for live/capital-changing controls.
- No live/legacy/Redis/exchange mutation path is introduced.

## GO/NO-GO

Codex must emit exactly one:

- `CODEX_DESIGN_HANDOFF_REVIEW_PASS`
- `CODEX_DESIGN_HANDOFF_REVIEW_FAIL`
