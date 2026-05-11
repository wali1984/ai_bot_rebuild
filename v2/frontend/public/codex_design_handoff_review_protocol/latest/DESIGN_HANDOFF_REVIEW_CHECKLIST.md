# Design Handoff Review Checklist

Codex must mark each item PASS, FAIL, or WARN with evidence pointers.

## Routing And Serving

- The default browser route `/` serves the intended V2 experience or intentionally redirects to the intended route.
- `/admin/mission-control?role=admin` is the main cockpit.
- `/admin/operator-proof-dashboard?role=admin` remains evidence/proof-only.
- The design is imported through `src/router.tsx`, `src/pages/registry.ts`, or the existing page/module route structure.
- No duplicate unused website folder is the only location of the new design.
- Vite is the documented frontend dev server for the visible UI.

## Enterprise Cockpit Quality

- Mission Control is a dense enterprise cockpit, not a raw markdown or placeholder artifact page.
- The global live-block banner is always visible and says live trading remains blocked/human-only.
- Risk, signal, execution, runtime, and readiness panels have compact, scannable information.
- Responsive/mobile behavior does not hide safety-critical status.
- The temporary loaded marker is visible only as an integration proof and is non-authoritative.

## TradingView / Chart Contract

- `TradingViewWidget` or an equivalent production chart surface is primary.
- Default symbol is `BINANCE:BTCUSDT` unless explicitly changed by a safe frontend config.
- External script cleanup prevents hot-reload duplicate widgets.
- Failure path shows `Chart unavailable. TradingView widget failed to load.` or a clearly equivalent fallback.
- Old SVG/static/proof chart is fallback-only, labeled `STATIC_PROOF_FIXTURE`, and not visible beside a healthy TradingView chart.

## Payload Truthfulness

- Every panel has a visible source label: `READONLY_MARKET_FEED`, `READONLY_ACCOUNT_FEED`, `RUNTIME_MONITOR_PAYLOAD`, `V2_PROOF_ARTIFACT`, `STATIC_PROOF_FIXTURE`, or `MISSING_EVIDENCE`.
- Every runtime value has freshness or a clear stale/missing marker.
- Design mock data is removed or explicitly downgraded to labeled fixture/evidence-gap state.
- Summaries do not replace raw evidence pointers.
- Dashboard payloads match the UI claims.

## Required Pages

- Monitor Center shows real status/freshness records or exact gaps.
- Trainer Prediction Monitor shows prediction IDs, feature snapshot IDs, confidence, model/checkpoint, freshness, and missing-evidence warnings.
- Signal Explainability shows natural-language explanation only when backed by evidence, otherwise explicit missing-evidence text.
- Config Admin classifies settings as `safe_to_edit`, `requires_validation`, `requires_human_approval`, `read_only`, or `remove_or_replace`.
- Build Validation and Codex Review Center show latest GO/NO-GO state.
- Exchange Manager, Risk Control, and live-readiness pages keep dangerous controls disabled/default-deny.

## Safety

- No legacy bot mutation.
- No Redis writes/deletes/trims and no Redis trim approval file creation.
- No service restarts.
- No exchange order/cancel/modify actions.
- No leverage, margin, or position-mode changes.
- No live key activation.
- No live trading enablement.
- No secret exposure.

## Validation

- `npm run typecheck` passes if frontend source changed.
- `npm run build` passes if frontend source changed.
- Playwright/Chromium smoke covers the main admin routes when dashboard/UI changed.
- Secret scan is clean.
- Safety scan confirms no live/legacy/Redis/exchange mutation path was added.
