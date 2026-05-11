# DATA_CONTRACT_MAP.md

Condensed companion to `claude_worklog/frontend_design/handoffs/2026-05-11/DATA_CONTRACT_ENFORCEMENT.md`.

Every panel introduced or referenced by the Claude Design handoff falls into one of seven source classes. The rules are absolute:
- `DESIGN_MOCK_DATA_TO_REMOVE` panels cannot ship.
- `STATIC_PROOF_FIXTURE` panels must show a visible "static fixture" badge.
- `MISSING_EVIDENCE` panels must name the missing source.
- Signal explanations may not guess.
- Every panel must show a freshness/source label.

## Summary by class

| Class | Count | Disposition |
|---|---:|---|
| `READONLY_MARKET_FEED` | 2 | TradingView widget + symbol-feed-derived telemetry |
| `READONLY_ACCOUNT_FEED` | 3 | Live-readiness banner state + kill-switch read + exchange manager state |
| `RUNTIME_MONITOR_PAYLOAD` | 5+ | runtime-monitor JSON drops; partial today, extension required |
| `V2_PROOF_ARTIFACT` | 25+ | preserved proof JSON under `v2/frontend/public/<feature>/latest/` |
| `STATIC_PROOF_FIXTURE` | 0 | none used in this handoff; reserved class |
| `MISSING_EVIDENCE` | 12 | each filed as a payload requirement in `NEW_PAYLOAD_REQUIREMENTS.md` |
| `DESIGN_MOCK_DATA_TO_REMOVE` | 8+ | every `data.jsx` constant; not imported |

## Key rule-enforcement checks

- TradingView remains primary chart. SVG design fallback is not lifted.
- Live-blocked banner derives from `/api/v1/risk/live-readiness` only. Design's hardcoded marquee strings are not lifted.
- Signal Explainability has no synthesized feature contributions; missing values render evidence-gap with artifact pointer.
- Monitor Center surfaces each missing field as a row-level evidence gap; no synthetic numbers.
- Config Admin / Risk Control / Strategy Admin dangerous-setting toggles remain gated by `dangerousControls.ts` (L4 / L5 classes) and the existing `DangerousControlPanel`.
- Mobile / iPhone Readiness derives PWA manifest + service-worker state from existing artifacts; the rest is filed as `MISSING_EVIDENCE`.

## Cross-reference

For per-page, per-panel classification, see `claude_worklog/frontend_design/handoffs/2026-05-11/DATA_CONTRACT_ENFORCEMENT.md`.
For payload specs of the 12 `MISSING_EVIDENCE` panels, see `claude_worklog/frontend_design/handoffs/2026-05-11/NEW_PAYLOAD_REQUIREMENTS.md`.
