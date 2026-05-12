IMPLEMENTATION_MAP

Frontend source changed:
- `v2/frontend/src/pages/operatorTruthComponents.tsx`
- `v2/frontend/src/pages/mission-control/index.tsx`
- `v2/frontend/src/pages/monitor-center/index.tsx`
- `v2/frontend/src/pages/trainer-prediction-monitor/index.tsx`
- `v2/frontend/src/pages/signal-explainability/index.tsx`
- `v2/frontend/src/styles.css`
- `v2/frontend/scripts/sync-proof-artifacts.mjs`

Implemented UI surfaces:
- `OperatorTruthCommandDeck`: first-screen runtime truth cockpit.
- `RuntimeTruthMatrix`: compact supervisor/trainer/signal/payload/live truth grid.
- `RouteTruthSummary`: route-level truth summary for Monitor Center, Trainer Prediction Monitor, and Signal Explainability.
- Collapsed raw process rows and payload freshness tables behind details sections.
- More prominent stale/missing/static classification cards.

Data truth preserved:
- Runtime values are still read from `v2/frontend/public/operator_truth/latest/operator_truth_payload.json`.
- Static proof fixtures remain labeled as `STATIC_PROOF_FIXTURE`.
- Missing evidence remains explicit and uses the no-guessing rule.
- No design mock data was imported as runtime truth.

Safety preserved:
- Live banner remains visible.
- Live trading remains `blocked_human_only`.
- Redis trim remains deferred/non-blocking.
- No legacy, Redis, exchange, leverage, margin, or live action was performed.
