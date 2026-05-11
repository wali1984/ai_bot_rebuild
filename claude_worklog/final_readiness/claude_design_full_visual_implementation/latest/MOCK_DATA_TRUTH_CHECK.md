# Mock Data Truth Check

Result: clean.

The implementation did not import Claude Design mock state from:

- `claude_worklog/frontend_design/handoffs/2026-05-11/data.jsx`
- design prototype `window.AIBOT` globals
- design-only subsystem arrays
- design-only telemetry strings
- prototype chart data

Runtime values now come from:

- `useCockpitPayload()`
- existing V2 public proof/runtime payloads
- existing `TradingViewWidget` read-only chart surface
- explicit evidence-gap panels when payloads are missing

Rules preserved:

- `DESIGN_MOCK_DATA` does not appear as runtime truth.
- missing signal/trainer/risk fields are not guessed.
- Signal Explainability displays: `Evidence missing — cannot explain without guessing.`
- `READONLY_MARKET_FEED`, `STATIC_PROOF_FIXTURE`, `V2_PROOF_ARTIFACT`, and `RUNTIME_MONITOR_PAYLOAD` source classifications remain visible through ribbons, badges, and panel copy.
