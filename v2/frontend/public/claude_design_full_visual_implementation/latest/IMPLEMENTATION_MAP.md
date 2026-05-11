# Implementation Map

Frontend files changed:

- `v2/frontend/src/pages/mission-control/index.tsx`
  - Full Mission Control composition converted to design command hero, subsystem strip, primary chart lane, risk boundary panel, and evidence grid.
- `v2/frontend/src/pages/cockpitComponents.tsx`
  - Shared `Panel` now renders the bracketed design panel structure and optional action chip area.
- `v2/frontend/src/pages/designShell.tsx`
  - New shared design shell for secondary admin pages.
- `v2/frontend/src/pages/monitor-center/index.tsx`
- `v2/frontend/src/pages/trainer-prediction-monitor/index.tsx`
- `v2/frontend/src/pages/signal-explainability/index.tsx`
- `v2/frontend/src/pages/risk-control/index.tsx`
- `v2/frontend/src/pages/config-admin/index.tsx`
- `v2/frontend/src/pages/build-validation-status/index.tsx`
- `v2/frontend/src/pages/claude-admin-ai/index.tsx`
- `v2/frontend/src/pages/mobile-iphone-readiness/index.tsx`
  - Secondary pages now use `DesignPageShell` and source/safety ribbons.
- `v2/frontend/src/styles.css`
  - Added design shell, command hero, subsystem strip, and dense panel layout styles.
- `v2/frontend/scripts/sync-proof-artifacts.mjs`
  - Syncs `claude_design_full_visual_implementation`.

Routes verified by smoke:

- `/`
- `/admin/mission-control?role=admin`
- `/admin/operator-proof-dashboard?role=admin`
- `/admin/monitor-center?role=admin`
- `/admin/trainer-prediction-monitor?role=admin`
- `/admin/signal-explainability?role=admin`
- `/admin/config-admin?role=admin`
- `/admin/claude-admin-ai?role=admin`
- `/admin/mobile-iphone-readiness?role=admin`
