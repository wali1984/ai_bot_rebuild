# Codex Design Handoff Review Protocol

Status: `CODEX_DESIGN_HANDOFF_REVIEW_PROTOCOL_READY`

Generated: 2026-05-11T21:18:32Z

This protocol defines how Codex reviews Claude Design handoffs and enterprise UI redesign work while Claude remains the primary builder. It is review-only policy. It does not implement UI, dispatch a feature task, modify legacy, mutate Redis, or touch exchange/live state.

## Scope

Codex must review design handoff ingestion, Mission Control enterprise UI redesigns, TradingView replacement work, payload truthfulness, safety banners, Monitor Center, Trainer Prediction Monitor, Signal Explainability, Config Admin, and no-placeholder rules.

Codex must treat design prototype files under `claude_worklog/frontend_design/handoffs/<latest>/` as visual/reference artifacts only. They are not production React/Vite source, and mock `data.jsx` content is not runtime truth.

## Required Inputs

- `claude_worklog/frontend_design/handoffs/<latest>/CLAUDE_CODE_PROMPT.md`
- `claude_worklog/frontend_design/handoffs/<latest>/README.md`
- Latest handoff JSX references in `claude_worklog/frontend_design/handoffs/<latest>/`
- `v2/frontend/package.json`
- `v2/frontend/src/main.tsx`
- `v2/frontend/src/router.tsx`
- `v2/frontend/src/pages/registry.ts`
- `v2/frontend/src/pages/mission-control/`
- `v2/frontend/src/pages/cockpitComponents.tsx`
- `v2/frontend/src/pages/cockpitData.ts`
- `v2/frontend/src/components/charts/TradingViewWidget.tsx`
- `v2/frontend/src/components/banners/`
- `v2/frontend/src/components/layout/`
- Relevant dashboard payloads under `v2/frontend/public/**/operator_dashboard_payload.json`
- Final readiness artifacts under `claude_worklog/final_readiness/enterprise_ui_polish/latest/`

## Review Rules

Codex must fail the review if any of these are true:

- The new design exists only in a duplicate or standalone folder and is not wired through the real Vite router.
- `/`, `/admin`, or `/admin/mission-control?role=admin` still serve the wrong default surface after the handoff claims integration.
- TradingView is not the primary cockpit chart while a legacy/static chart remains visible in the normal healthy path.
- The old SVG/static chart is presented as authoritative instead of fallback-only.
- A prototype mock value from `data.jsx` or equivalent is rendered as real runtime truth.
- Any page is placeholder-only without an explicit evidence-gap label and source/task pointer.
- Mission Control, Monitor Center, Trainer Prediction Monitor, Signal Explainability, Config Admin, Build Validation, and Mobile/iPhone readiness lose route visibility.
- The global live-block banner is missing, removable, misleading, or no longer says live trading is blocked/human-only.
- A dangerous admin control is present without read-only/disabled/default-deny behavior and explicit approval classification.
- Signal or trainer explanation text guesses causal reasons without raw evidence pointers.
- Payload values are displayed without source and freshness labels.
- The implementation adds Redis writes, legacy mutation, exchange actions, leverage/margin changes, live-key activation, or live enablement.

## Evidence Standard

Summaries are navigation aids only. Codex findings must point to raw source, route definitions, payload JSON, tests, or command output. For browser-facing claims, Codex should cite the route/component path and, when available, Playwright or build output.

## Expected Codex Outputs

For each design-handoff review, Codex should emit:

- `CODEX_DESIGN_HANDOFF_REVIEW.md`
- `CODEX_DESIGN_HANDOFF_GO_NO_GO.md`

The GO/NO-GO file must contain exactly one line:

`CODEX_DESIGN_HANDOFF_REVIEW_PASS`

or

`CODEX_DESIGN_HANDOFF_REVIEW_FAIL`

## Safety Boundary

This protocol is review-only. Codex must not implement UI inside the review task, must not mutate legacy, must not mutate Redis, must not create Redis trim approval files, must not place/cancel/modify exchange orders, must not change leverage/margin/position mode, must not enable live trading, and must not expose secrets.
