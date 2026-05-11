# Validation Results

Commands run:

- `cd v2/frontend && npm run typecheck` — passed.
- `cd v2/frontend && npm run sync:proof-artifacts` — passed; synced `claude_design_full_visual_implementation`.
- `cd v2/frontend && npm run build` — passed.
- Playwright/Chromium smoke for required routes — passed.
- JSON validation for source and public dashboard payloads — passed.
- `git diff --check` — passed.
- high-confidence secret scan — clean.
- safety scan for live/exchange/capital/Redis mutation strings in modified frontend sources — clean.
- Redis trim approval absence check — `REDIS_TRIM_APPROVAL_ABSENT_OK`.

Playwright smoke result:

```json
{
  "rootUrl": "http://127.0.0.1:5173/admin/mission-control?role=admin",
  "marker": "AI BOT V2 Modern Dashboard Loaded",
  "heroVisible": true,
  "liveBannerIncludesBlocked": true,
  "chartVisible": true,
  "fallbackVisible": false,
  "proofDashboardVisible": true
}
```

Expanded route smoke:

```json
{
  "routes": [
    "/",
    "/admin",
    "/admin/mission-control?role=admin",
    "/admin/operator-proof-dashboard?role=admin",
    "/admin/monitor-center?role=admin",
    "/admin/trainer-prediction-monitor?role=admin",
    "/admin/signal-explainability?role=admin",
    "/admin/config-admin?role=admin",
    "/admin/claude-admin-ai?role=admin",
    "/admin/mobile-iphone-readiness?role=admin",
    "/admin/risk-control?role=admin"
  ],
  "visual": {
    "missionHeroVisible": true,
    "subsystemCards": 6,
    "bracketedPanels": 18,
    "tradingViewVisible": true,
    "fallbackVisible": false,
    "serviceWorkers": 0,
    "riskControlDangerousPanelVisible": true,
    "riskControlDisabledDangerousButtons": 3
  }
}
```
