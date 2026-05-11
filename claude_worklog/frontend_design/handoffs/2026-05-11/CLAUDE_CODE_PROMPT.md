# Claude Code — Authoritative Implementation Brief

> This file is the **source of truth** for the implementation work. The README documents the design; this document documents the contract. If anything in the README conflicts with this file, this file wins.

## Working directory

```bash
cd "$HOME/Desktop/AI BOT REBUILD"
```

## Next target

`INGEST_CLAUDE_DESIGN_HANDOFF_AND_UPDATE_V2_WEBSITE_READY`

Ingest the Claude Design output, map it to current V2 frontend routes/components/payloads, implement only verified UI changes, remove/label mock data, and keep all safety gates. Do not touch legacy bot. Do not write old Redis. Do not place/cancel orders. Do not enable live trading.

---

## Hard constraints

- Do not modify `/home/wali/Desktop/AI BOT`.
- Do not write/delete legacy Redis keys.
- Do not create Redis trim approval file.
- Do not run Redis `XTRIM` / `DEL` / `XDEL` / `FLUSH` / `SET` / `HSET` / `XADD`.
- Do not restart live trainer/trader/orchestrator/Redis/VPN.
- Do not place/cancel/modify exchange orders.
- Do not change leverage.
- Do not change margin mode or position mode.
- Do not activate live trading keys.
- Do not enable live trading.
- Do not deploy live execution externally.
- Do not expose or commit secrets.
- Work only inside `AI BOT REBUILD`.
- Live trading remains `blocked_human_only`.

## Context

A Claude Design web-chat handoff has been provided under:

```
claude_worklog/frontend_design/handoffs/<latest>/
```

Your job is to translate design into V2 frontend implementation safely.

- Do not blindly copy the design prototype.
- Do not preserve fake/mock/demo data as if real.
- Do not keep placeholder-only pages.
- Do not break existing payload wiring.
- Do not remove safety warnings.

---

## PART A — Inspect design package

Inspect latest handoff folder:

```
claude_worklog/frontend_design/handoffs/
```

If a source zip exists, extract it under that handoff folder only.

Create:

```
claude_worklog/frontend_design/handoffs/<latest>/CODE_INGESTION_ANALYSIS.md
```

Document:
- files in design package
- routes/components present
- mock data present
- placeholder components present
- current V2 components affected
- payloads required
- missing backend/data contracts
- implementation risk

---

## PART B — Map design to current V2 frontend

Inspect current frontend:

```
v2/frontend/
```

Create:

```
claude_worklog/frontend_design/handoffs/<latest>/CURRENT_FRONTEND_ROUTE_MAP.md
```

Map:
- design page → V2 route
- design component → V2 component/file
- design data → V2 public payload/API
- design mock data → real payload or evidence gap
- design placeholder → remove, replace, or evidence gap

Required main route:
- `/admin/mission-control?role=admin` remains main cockpit.

Required evidence route:
- `/admin/operator-proof-dashboard?role=admin` remains evidence/proof page only.

---

## PART C — Data contract enforcement

Create:

```
claude_worklog/frontend_design/handoffs/<latest>/DATA_CONTRACT_ENFORCEMENT.md
```

For every UI panel, classify data source:
- `READONLY_MARKET_FEED`
- `READONLY_ACCOUNT_FEED`
- `RUNTIME_MONITOR_PAYLOAD`
- `V2_PROOF_ARTIFACT`
- `STATIC_PROOF_FIXTURE`
- `MISSING_EVIDENCE`
- `DESIGN_MOCK_DATA_TO_REMOVE`

Rules:
- `DESIGN_MOCK_DATA_TO_REMOVE` cannot ship as real.
- `STATIC_PROOF_FIXTURE` must be labeled visibly.
- `MISSING_EVIDENCE` must say exactly what source/task is missing.
- Signal explanations must not guess.
- Every panel must show freshness/source labels.

---

## PART D — Implement frontend changes

Implement design improvements inside V2 frontend only.

Required:
- preserve global live blocked banner
- preserve role/admin routing
- preserve current proof/evidence sections
- replace old/static/SVG chart as primary if TradingView/lightweight chart exists
- keep fallback chart only as clearly labeled fallback
- remove placeholder-only content
- convert mock-only panels to evidence gaps
- wire components to existing payloads where available
- add new payload requirements where missing
- maintain responsive/mobile layout
- keep future iPhone/PWA path

Important:
- If current codebase uses TypeScript, implement TypeScript.
- If current codebase uses JS/JSX, follow current project style.
- Do not introduce a new frontend framework unless already approved.

---

## PART E — Required pages/features checklist

Verify these exist or are explicit evidence gaps:

- Mission Control
- Monitor Center
- Coverage / System Atlas
- Script Registry
- Trainer Prediction Monitor
- Signal Explainability
- Symbols
- Signals
- Executions
- Positions
- Risk Control
- Config Admin
- Strategy Admin
- Trainer Admin
- Orchestrator Admin
- Execution Admin
- Paper Trading
- Replay
- Audit Ledger
- System Health
- Live Readiness
- Claude Admin AI
- Ollama Local Assistant
- Codex Review Center
- Build / Validation Status
- Mobile / iPhone Readiness
- Exchange Manager
- External / Manual Position Quarantine

Create:

```
claude_worklog/frontend_design/handoffs/<latest>/PAGE_FEATURE_COVERAGE.md
```

---

## PART F — Claude Design output normalization

If the design package includes files like:
- `app.jsx`
- `data.jsx`
- `mission-control.jsx`
- `module-placeholder.jsx`
- `pages-admin.jsx`
- `pages-ai.jsx`
- `pages-inspect.jsx`
- `pages-operate.jsx`
- `pages-system.jsx`
- `primitives.jsx`
- `risk-control.jsx`
- `signal-explainability.jsx`
- `tweaks-panel.jsx`

Then:
- Treat them as design reference.
- Do not copy window-global architecture directly if V2 uses modules/routes.
- Extract visual patterns and components.
- Replace `module-placeholder` behavior with real route components or explicit evidence gap.
- Convert static data in `data.jsx` into typed fixture-only examples, or remove.
- Never let `data.jsx` mock metrics appear as live runtime truth.
- Use actual V2 payloads from `v2/frontend/public` or backend API where available.

---

## PART G — Dashboard payloads

If new panels require payloads, create or update **payload requirement docs**, not fake data.

Create:

```
claude_worklog/frontend_design/handoffs/<latest>/NEW_PAYLOAD_REQUIREMENTS.md
```

Each payload requirement must include:
- payload name
- route/page
- fields
- source
- freshness requirement
- source type
- backend owner
- missing evidence behavior

---

## PART H — Validation

Run:
- `npm run sync:proof-artifacts` if needed
- `npm run typecheck`
- `npm run build`
- Playwright/Chromium smoke if available
- visual smoke for `/admin/mission-control?role=admin`
- visual smoke for `/admin/operator-proof-dashboard?role=admin`
- high-confidence secret scan clean
- safety scan confirms no live/exchange/capital action
- Redis trim approval absence check
- `git diff --check`

If frontend changed, smoke routes:
- `/admin/mission-control?role=admin`
- `/admin/operator-proof-dashboard?role=admin`
- `/admin/monitor-center?role=admin`
- `/admin/trainer-prediction-monitor?role=admin`
- `/admin/signal-explainability?role=admin`
- `/admin/config-admin?role=admin`
- `/admin/exchange-manager?role=admin`
- `/admin/mobile-iphone-readiness?role=admin`
- `/admin/build-validation-status?role=admin`

---

## PART I — Required final outputs

Create:

```
claude_worklog/final_readiness/claude_design_to_code_handoff/latest/CLAUDE_DESIGN_TO_CODE_HANDOFF_REPORT.md
claude_worklog/final_readiness/claude_design_to_code_handoff/latest/GO_NO_GO.md
claude_worklog/final_readiness/claude_design_to_code_handoff/latest/IMPLEMENTATION_MAP.md
claude_worklog/final_readiness/claude_design_to_code_handoff/latest/DATA_CONTRACT_MAP.md
claude_worklog/final_readiness/claude_design_to_code_handoff/latest/PLACEHOLDER_REMOVAL_REPORT.md
claude_worklog/final_readiness/claude_design_to_code_handoff/latest/MOCK_DATA_REMOVAL_REPORT.md
claude_worklog/final_readiness/claude_design_to_code_handoff/latest/PAGE_FEATURE_COVERAGE.md
claude_worklog/final_readiness/claude_design_to_code_handoff/latest/TRADINGVIEW_REPLACEMENT_REPORT.md
claude_worklog/final_readiness/claude_design_to_code_handoff/latest/MOBILE_IPHONE_READINESS_NOTES.md
claude_worklog/final_readiness/claude_design_to_code_handoff/latest/CODEX_REVIEW_REQUEST.md
```

`GO_NO_GO.md` must contain exactly one line:

```
CLAUDE_DESIGN_TO_CODE_HANDOFF_IMPLEMENTED_READY
```

or

```
CLAUDE_DESIGN_TO_CODE_HANDOFF_IMPLEMENTED_BLOCKED
```

Do not mark READY unless:
- design handoff inspected
- implementation map created
- mock data removed or labeled
- placeholder-only pages removed or replaced with evidence gaps
- safety banner preserved
- V2 routes still work
- typecheck/build pass
- smoke tests pass
- live remains blocked
- Redis trim remains deferred/non-blocking
- Codex review requested

---

## PART J — Codex review

After implementation, run Codex review.

Codex must challenge:
- whether any design mock data is presented as real
- whether old chart remains incorrectly primary
- whether Signal Explainability guesses
- whether Monitor Center lacks required script/monitor fields
- whether Config Admin lacks dangerous-setting approval classification
- whether pages are placeholder-only
- whether live/Redis/exchange safety was violated
- whether mobile/iPhone future path is preserved

Required Codex outputs:

```
claude_worklog/final_readiness/claude_design_to_code_handoff/latest/CODEX_DESIGN_HANDOFF_REVIEW.md
claude_worklog/final_readiness/claude_design_to_code_handoff/latest/CODEX_GO_NO_GO.md
```

`CODEX_GO_NO_GO.md` must contain exactly one line:

```
CLAUDE_DESIGN_TO_CODE_HANDOFF_CODEX_PASS
```

or

```
CLAUDE_DESIGN_TO_CODE_HANDOFF_CODEX_FAIL
```

---

## PART K — Commit/push

Commit and push only after validation passes.

Final report must include:
- design handoff ingested: yes/no
- pages updated
- mock data removed/labeled
- placeholders removed
- TradingView primary: yes/no
- safety banner preserved: yes/no
- data contracts mapped: yes/no
- mobile/iPhone path preserved: yes/no
- typecheck/build passed: yes/no
- Codex review requested/passed: yes/no
- live gate status
- Redis trim status
- latest commit hash
- git clean
===== END FILE: CLAUDE_CODE_PROMPT.md =====

