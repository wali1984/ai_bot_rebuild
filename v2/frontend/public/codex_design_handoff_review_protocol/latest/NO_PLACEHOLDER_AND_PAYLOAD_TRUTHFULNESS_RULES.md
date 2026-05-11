# No-Placeholder And Payload Truthfulness Rules

Codex must enforce these rules when reviewing design handoff ingestion or enterprise UI redesign work.

## Placeholder Rules

- Placeholder-only pages cannot pass.
- A route may show missing data only if it states the exact missing source, expected payload, and follow-up task.
- Prototype copy such as lorem ipsum, fake KPI values, fake PnL, fake trainer confidence, or fake signal rationales cannot be shown as real.
- A fixture can be shown only with a visible `STATIC_PROOF_FIXTURE` source label.
- A missing payload must be labeled `MISSING_EVIDENCE`, not silently replaced with mock data.

## Payload Truthfulness Rules

- Source labels must be visible near the values they qualify.
- Freshness timestamps must be visible or stale/missing must be explicit.
- Read-only market data must be labeled `READONLY_MARKET_FEED`.
- Read-only account data must be labeled `READONLY_ACCOUNT_FEED`.
- Runtime monitor data must be labeled `RUNTIME_MONITOR_PAYLOAD`.
- Final-readiness proof payloads must be labeled `V2_PROOF_ARTIFACT`.
- Static proof candles/charts must be labeled `STATIC_PROOF_FIXTURE`.

## Explainability Rules

- Signal explanations must cite raw prediction/signal/risk/execution evidence or say evidence is missing.
- Trainer prediction panels must show prediction ID, feature snapshot ID, model/checkpoint, confidence, calibration/freshness, and missing-evidence warnings.
- Config Admin must classify settings by edit safety and cannot expose live/capital-changing controls as ordinary toggles.

## Safety Banner Rules

- Live trading status must remain `blocked_human_only`.
- The live-block banner must be global, visible, and not user-removable.
- Any route that touches exchange/risk/config/live-readiness concepts must show disabled/default-deny dangerous controls.
