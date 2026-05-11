# AI BOT V2 — Claude Code Handoff Bundle

Single-file bundle containing the full design handoff. Each file below is delimited by a fenced block with a path header. To unpack, split on the `===== FILE: <path> =====` markers and write each chunk to that path.

## How Claude Code should ingest this

1. Read this entire file.
2. For each `===== FILE: <path> =====` section, write the body (everything up to the next marker) to `claude_worklog/frontend_design/handoffs/<latest>/<path>`.
3. Then follow the instructions in `CLAUDE_CODE_PROMPT.md` exactly.

---

===== FILE: README.md =====
# Handoff: AI BOT V2 — Mission Control & Admin Console

## Overview
This handoff packages the **AI BOT V2 Mission Control** front-end design — a dark, terminal-flavored operator cockpit for a trading bot system. It covers the main Mission Control surface, the operator proof / evidence dashboard, and all admin/inspect/operate/system/AI sub-pages defined in the V2 information architecture.

The work to be done by Claude Code is **NOT** a fresh build — it is an **ingestion + safe re-implementation** of these designs into the existing `v2/frontend/` codebase at `$HOME/Desktop/AI BOT REBUILD`, under a strict set of safety constraints (no live trading, no Redis writes, no order placement, no secret exposure, no touching the legacy bot folder).

The full, authoritative implementation brief — including hard constraints, required pages, required validation, required output files, and Codex review requirements — is in:

- **`CLAUDE_CODE_PROMPT.md`** — read this first, it is the source of truth.

This README documents the design itself; `CLAUDE_CODE_PROMPT.md` documents the implementation contract.

## About the Design Files
The `.jsx` + `index.html` files in this bundle are **design references created in HTML/React-via-Babel**. They are inline-Babel prototypes intended to convey look, layout, interaction, and information architecture. They are **not** production code and **must not be lifted into `v2/frontend/` verbatim**.

The task is to:
1. Read the prototypes as reference for visual language and component composition.
2. Re-implement the patterns inside the existing V2 frontend using **its** module system, routing, and language (TypeScript if V2 is TS; JS/JSX if V2 is JS).
3. Wire every panel to a real V2 payload, a labeled static fixture, or a clearly-labeled `MISSING_EVIDENCE` gap — **never** to the mock data in `data.jsx`.

If `v2/frontend/` has no equivalent surface yet for a given page, that page should be created as a placeholder route with an explicit evidence-gap state — not with fabricated metrics.

## Fidelity
**High-fidelity.** The prototypes are pixel-considered:
- Final color tokens (dark / light / terminal themes)
- Final typography (IBM Plex Sans + IBM Plex Mono + IBM Plex Sans Condensed)
- Final spacing, borders, hatched warning surfaces, corner-bracket panel chrome
- Final panel/table/chip/button primitives in `primitives.jsx`
- Final interaction states for the major panels (Mission Control KPI strip, Signal Explainability, Risk Control)

The developer should recreate the UI **pixel-faithfully** using the V2 codebase's existing component library / CSS approach. Where V2 already has a primitive (e.g. a Panel or Chip), prefer V2's version and apply these design tokens to it rather than introducing a parallel system.

## Design system summary

### Themes
Three themes, all driven by CSS custom properties on `[data-theme="…"]`:
- `dark` (default) — near-black `#0A0D12` base, amber accent `#F5A524`
- `light` — warm paper `#F2EFE9` base, burnt-amber accent `#B26A00`
- `terminal` — pure black + phosphor amber `#E8C57A` (mono UI)

### Color tokens (dark theme reference)
| Token | Value | Use |
|---|---|---|
| `--bg` | `#0A0D12` | page background |
| `--surface` | `#10141B` | app surface |
| `--panel` | `#141921` | panel fill |
| `--panel-2` | `#181E27` | panel header / hover |
| `--border` | `#232A35` | hairline |
| `--border-strong` | `#2F3845` | emphasized hairline |
| `--text` | `#E7ECF2` | primary text |
| `--text-mid` | `#98A0AC` | secondary text |
| `--text-dim` | `#5B6471` | tertiary text |
| `--text-faint` | `#3D4552` | disabled text |
| `--accent` | `#F5A524` | attention / amber |
| `--accent-2` | `oklch(0.78 0.13 60)` | secondary accent |
| `--ok` | `oklch(0.78 0.13 155)` | success / green |
| `--block` | `oklch(0.68 0.20 25)` | block / red |
| `--warn` | `oklch(0.82 0.13 90)` | warn / yellow |
| `--paper` | `oklch(0.74 0.11 250)` | paper-trading / blue |
| `--hatch` / `--hatch-strong` | amber-on-transparent stripes | warning surfaces |

### Typography
- Sans: **IBM Plex Sans** (300/400/500/600/700) — body
- Mono: **IBM Plex Mono** (300/400/500/600) — numbers, labels, eyebrows, chips, buttons, table headers
- Condensed: **IBM Plex Sans Condensed** (500/600) — dense table labels

Utility classes: `.mono`, `.num` (tabular nums), `.cond`, `.eyebrow` (10px / 0.14em / uppercase), `.label-mono` (10.5px / 0.06em / uppercase).

### Layout
- App root: CSS grid `224px sidebar | 1fr content`, with a top **blocked-strip** marquee that always reads `LIVE TRADING BLOCKED — HUMAN APPROVAL ONLY`.
- Panels: `.panel` + `.panel-head` + `.panel-body`, optional `.bracketed` corner brackets for cockpit-critical sections.
- Page background grid: 32px × 32px faint grid lines via `.grid-bg`.

## Screens / Views

The IA splits into five page groups (matching the `pages-*.jsx` files) plus the always-mounted Mission Control and Signal Explainability surfaces. For the full required-pages checklist and route map, see `CLAUDE_CODE_PROMPT.md` Part E.

### Mission Control (`mission-control.jsx`)
- **Route:** `/admin/mission-control?role=admin` (main cockpit)
- **Purpose:** at-a-glance operator status across live gate, kill-switch, risk envelope, account telemetry, paper-vs-live, recent signals, recent executions, system health.
- **Layout:** KPI strip across the top, primary chart + signal stream in the middle, recent activity tables along the bottom.
- **Chart:** prototype uses an SVG fallback. Per the prompt, the **real implementation must use TradingView / lightweight-charts as primary** and only keep the SVG as a clearly-labeled fallback.
- **Data source policy:** every panel must declare `READONLY_MARKET_FEED` | `READONLY_ACCOUNT_FEED` | `RUNTIME_MONITOR_PAYLOAD` | `V2_PROOF_ARTIFACT` | `STATIC_PROOF_FIXTURE` | `MISSING_EVIDENCE` and show a visible freshness/source label.

### Operator Proof Dashboard (`pages-inspect.jsx` family)
- **Route:** `/admin/operator-proof-dashboard?role=admin`
- **Purpose:** evidence / proof page only. Lists V2 proof artifacts, fixtures, and explicit evidence gaps. Never fabricates.

### Operate (`pages-operate.jsx`)
Symbols • Signals • Executions • Positions • Risk Control • Paper Trading • Replay

### Inspect (`pages-inspect.jsx`)
Monitor Center • Coverage / System Atlas • Script Registry • Trainer Prediction Monitor • Signal Explainability • Audit Ledger

### Admin (`pages-admin.jsx`)
Config Admin • Strategy Admin • Trainer Admin • Orchestrator Admin • Execution Admin • Exchange Manager • External / Manual Position Quarantine

### AI (`pages-ai.jsx`)
Claude Admin AI • Ollama Local Assistant • Codex Review Center

### System (`pages-system.jsx`)
System Health • Live Readiness • Build / Validation Status • Mobile / iPhone Readiness

### Signal Explainability (`signal-explainability.jsx`)
Per-signal feature attribution, model version, fixture freshness. **Must not guess** — if a feature contribution is not available from a real artifact, render `MISSING_EVIDENCE` instead of filler text.

### Risk Control (`risk-control.jsx`)
Risk envelope, per-symbol caps, drawdown gates, kill-switch state.

## Components / primitives (`primitives.jsx`)
Reusable building blocks the prototypes assume:
- `<Panel>` with optional `bracketed` corners and `panel-head` row
- KPI tiles (number + delta + sparkline + freshness label)
- `<Chip>` variants: `solid-block`, `solid-warn`, `solid-ok`, `solid-paper`, plain
- `<Tag>` / `<DotStatus>` (pulse dot for live status)
- `.data` table style (mono headers, tabular nums, hover row)
- `.input`, `.btn` (default / `primary` / `danger`)
- Hatched surfaces (`.hatch`, `.hatch-strong`) for any warning band — including the global blocked-strip marquee
- `module-placeholder.jsx` — **must be replaced** in V2 with either a real route component or a labeled evidence-gap component; the prompt is explicit that placeholder-only pages cannot ship.

## Interactions & Behavior
- Theme switching via `data-theme` attribute on `<html>` (dark / light / terminal); persist user choice.
- Marquee `LIVE BLOCKED` strip is global and **must not be removable** by any route.
- Tick-flash animation on number updates (`.tick-flash` keyframes) for any value driven by a live payload.
- Pulse dots (`.pulse`) for live-status indicators.
- Tweaks panel (`tweaks-panel.jsx`) is a **design-prototype-only** affordance for swatch/theme exploration; **do not ship the Tweaks panel into V2** — strip it on ingestion.

## State Management
- Theme: persisted client-side (e.g. `localStorage`), respecting `#theme-default` JSON if present.
- All live data: V2 payloads as defined in `CLAUDE_CODE_PROMPT.md` Part C (Data Contract Enforcement) and Part G (New Payload Requirements). The prototypes' `data.jsx` is a **fixture-only reference** and must be removed or converted to a typed fixture; it must never appear as live runtime truth.

## Design Tokens
See "Design system summary" above. All values are encoded as CSS custom properties on `:root` / `[data-theme="…"]` in `index.html` — lift the token map verbatim into V2's token layer.

## Assets
- Fonts: Google Fonts — IBM Plex Sans, IBM Plex Mono, IBM Plex Sans Condensed. Self-host in V2 if the existing frontend self-hosts fonts; otherwise mirror the `<link>` preconnect + family used here.
- Icons: none baked in — the prototypes deliberately use type + dots + hatching instead of icons. Continue this pattern in V2.
- No external images.

## Files in this bundle
- `index.html` — root + theme tokens + script loading order
- `app.jsx` — app shell, routing skeleton, sidebar
- `data.jsx` — **fixture-only** mock data (must not ship as live)
- `primitives.jsx` — shared primitives
- `mission-control.jsx` — main cockpit
- `signal-explainability.jsx` — per-signal attribution
- `risk-control.jsx` — risk envelope panel
- `pages-operate.jsx` — Symbols / Signals / Executions / Positions / Paper / Replay
- `pages-inspect.jsx` — Monitor / Coverage / Script Registry / Trainer Monitor / Audit Ledger / Operator Proof
- `pages-admin.jsx` — Config / Strategy / Trainer / Orchestrator / Execution / Exchange / Quarantine
- `pages-ai.jsx` — Claude Admin / Ollama / Codex Review
- `pages-system.jsx` — System Health / Live Readiness / Build Validation / Mobile Readiness
- `module-placeholder.jsx` — placeholder shell (must be replaced in V2)
- `tweaks-panel.jsx` — **design-tool-only**, do not ship
- `CLAUDE_CODE_PROMPT.md` — **authoritative implementation brief** (read this first)

## How to run the prototype locally
Open `index.html` in any modern browser. All scripts are loaded via Babel-standalone from a CDN; no build step is required for the reference prototype. Do not use this load path in V2 — V2 must compile JSX/TSX at build time.
===== END FILE: README.md =====

===== FILE: CLAUDE_CODE_PROMPT.md =====
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

===== FILE: index.html =====
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>AI BOT V2 — Mission Control</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=IBM+Plex+Sans:wght@300;400;500;600;700&family=IBM+Plex+Sans+Condensed:wght@500;600&display=swap" rel="stylesheet" />

<script src="https://unpkg.com/react@18.3.1/umd/react.development.js" integrity="sha384-hD6/rw4ppMLGNu3tX5cjIb+uRZ7UkRJ6BPkLpg4hAu/6onKUg4lLsHAs9EBPT82L" crossorigin="anonymous"></script>
<script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js" integrity="sha384-u6aeetuaXnQ38mYT8rp6sbXaQe3NL9t+IBXmnYxwkUI2Hw4bsp2Wvmx4yRQF1uAm" crossorigin="anonymous"></script>
<script src="https://unpkg.com/@babel/standalone@7.29.0/babel.min.js" integrity="sha384-m08KidiNqLdpJqLq95G/LEi8Qvjl/xUYll3QILypMoQ65QorJ9Lvtp2RXYGBFj1y" crossorigin="anonymous"></script>

<style>
  :root, [data-theme="dark"] {
    --bg:        #0A0D12;
    --surface:   #10141B;
    --panel:     #141921;
    --panel-2:   #181E27;
    --border:    #232A35;
    --border-strong: #2F3845;
    --text:      #E7ECF2;
    --text-mid:  #98A0AC;
    --text-dim:  #5B6471;
    --text-faint:#3D4552;
    --accent:    #F5A524;          /* amber — attention */
    --accent-2:  oklch(0.78 0.13 60);
    --ok:        oklch(0.78 0.13 155);
    --block:     oklch(0.68 0.20 25);
    --warn:      oklch(0.82 0.13 90);
    --paper:     oklch(0.74 0.11 250);
    --grid-line: rgba(255,255,255,0.025);
    --hatch:     rgba(245, 165, 36, 0.10);
    --hatch-strong: rgba(245, 165, 36, 0.18);
    --is-mono-ui: 0;
  }
  [data-theme="light"] {
    --bg:        #F2EFE9;
    --surface:   #ECE8E0;
    --panel:     #F8F5EF;
    --panel-2:   #F1EDE4;
    --border:    #D9D3C5;
    --border-strong: #BFB7A4;
    --text:      #1A1D23;
    --text-mid:  #5A6371;
    --text-dim:  #8C95A2;
    --text-faint:#B5BCC7;
    --accent:    #B26A00;
    --accent-2:  oklch(0.55 0.13 60);
    --ok:        oklch(0.50 0.13 155);
    --block:     oklch(0.50 0.18 25);
    --warn:      oklch(0.55 0.13 90);
    --paper:     oklch(0.48 0.13 250);
    --grid-line: rgba(0,0,0,0.04);
    --hatch:     rgba(178, 106, 0, 0.12);
    --hatch-strong: rgba(178, 106, 0, 0.22);
    --is-mono-ui: 0;
  }
  [data-theme="terminal"] {
    --bg:        #000000;
    --surface:   #050505;
    --panel:     #0A0A0A;
    --panel-2:   #0F0F0F;
    --border:    #1E1E1E;
    --border-strong: #2B2B2B;
    --text:      #E8C57A;          /* phosphor amber */
    --text-mid:  #B08A3E;
    --text-dim:  #6A5023;
    --text-faint:#3D2E14;
    --accent:    #F5C56A;
    --accent-2:  #F5C56A;
    --ok:        #6ADB6A;
    --block:     #FF5050;
    --warn:      #F5C56A;
    --paper:     #6AC8E6;
    --grid-line: rgba(245,197,106,0.05);
    --hatch:     rgba(245, 197, 106, 0.10);
    --hatch-strong: rgba(245, 197, 106, 0.22);
    --is-mono-ui: 1;
  }

  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: var(--bg); color: var(--text); }
  body {
    font-family: "IBM Plex Sans", system-ui, sans-serif;
    font-size: 13px;
    line-height: 1.45;
    font-feature-settings: "ss01", "ss02";
    -webkit-font-smoothing: antialiased;
    min-height: 100vh;
    overflow-x: hidden;
  }
  [data-theme="terminal"] body {
    font-family: "IBM Plex Mono", ui-monospace, monospace;
  }
  .mono { font-family: "IBM Plex Mono", ui-monospace, monospace; font-feature-settings: "ss02", "zero"; }
  .num  { font-variant-numeric: tabular-nums; font-feature-settings: "tnum", "zero"; font-family: "IBM Plex Mono", ui-monospace, monospace; }
  .cond { font-family: "IBM Plex Sans Condensed", "IBM Plex Sans", sans-serif; }
  [data-theme="terminal"] .cond { font-family: "IBM Plex Mono", ui-monospace, monospace; }

  a { color: inherit; text-decoration: none; }
  button { font: inherit; color: inherit; background: none; border: 0; cursor: pointer; padding: 0; }

  /* —— global type utilities —— */
  .eyebrow {
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-size: 10px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--text-dim);
    font-weight: 500;
  }
  .label-mono {
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-size: 10.5px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--text-mid);
  }
  .hr { height: 1px; background: var(--border); }
  .hr-strong { height: 1px; background: var(--border-strong); }

  /* —— hatched stripes for warning surfaces —— */
  .hatch {
    background-image: repeating-linear-gradient(
      135deg,
      var(--hatch) 0 6px,
      transparent 6px 12px
    );
  }
  .hatch-strong {
    background-image: repeating-linear-gradient(
      135deg,
      var(--hatch-strong) 0 8px,
      transparent 8px 16px
    );
  }

  /* —— page grid background —— */
  .grid-bg {
    background-image:
      linear-gradient(var(--grid-line) 1px, transparent 1px),
      linear-gradient(90deg, var(--grid-line) 1px, transparent 1px);
    background-size: 32px 32px;
    background-position: -1px -1px;
  }

  /* —— scrollbar —— */
  ::-webkit-scrollbar { width: 8px; height: 8px; }
  ::-webkit-scrollbar-track { background: var(--bg); }
  ::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 0; }
  ::-webkit-scrollbar-thumb:hover { background: var(--text-faint); }

  /* —— panel —— */
  .panel {
    background: var(--panel);
    border: 1px solid var(--border);
    position: relative;
  }
  .panel-head {
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 14px;
    border-bottom: 1px solid var(--border);
    background: var(--panel-2);
  }
  .panel-title {
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-size: 10.5px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--text-mid);
    font-weight: 500;
  }
  .panel-body { padding: 14px; }

  /* —— corner brackets on key panels —— */
  .bracketed::before,
  .bracketed::after,
  .bracketed > .br-bl,
  .bracketed > .br-br {
    content: "";
    position: absolute;
    width: 10px; height: 10px;
    border: 1px solid var(--accent);
  }
  .bracketed::before { top: -1px; left: -1px; border-right: 0; border-bottom: 0; }
  .bracketed::after  { top: -1px; right: -1px; border-left: 0; border-bottom: 0; }
  .bracketed > .br-bl { bottom: -1px; left: -1px; border-right: 0; border-top: 0; }
  .bracketed > .br-br { bottom: -1px; right: -1px; border-left: 0; border-top: 0; }

  /* —— dots / pulse —— */
  .dot {
    display: inline-block; width: 6px; height: 6px; border-radius: 50%;
    background: var(--text-dim);
    box-shadow: 0 0 0 0 currentColor;
  }
  .dot.ok    { background: var(--ok);     color: var(--ok); }
  .dot.warn  { background: var(--warn);   color: var(--warn); }
  .dot.block { background: var(--block);  color: var(--block); }
  .dot.paper { background: var(--paper);  color: var(--paper); }
  .pulse {
    animation: pulse 2s ease-out infinite;
  }
  @keyframes pulse {
    0%   { box-shadow: 0 0 0 0   color-mix(in oklch, currentColor 50%, transparent); }
    70%  { box-shadow: 0 0 0 6px color-mix(in oklch, currentColor  0%, transparent); }
    100% { box-shadow: 0 0 0 0   color-mix(in oklch, currentColor  0%, transparent); }
  }

  /* —— tick fade for updating numbers —— */
  @keyframes tick-flash {
    0%   { background: color-mix(in oklch, var(--accent) 25%, transparent); }
    100% { background: transparent; }
  }
  .tick-flash { animation: tick-flash 0.5s ease-out; }

  /* —— badges —— */
  .chip {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 3px 8px;
    border: 1px solid var(--border-strong);
    background: var(--panel-2);
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-size: 10px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-mid);
    line-height: 1.2;
  }
  .chip.solid-block {
    background: var(--block);
    color: #fff;
    border-color: var(--block);
  }
  .chip.solid-warn {
    background: transparent;
    color: var(--accent);
    border-color: var(--accent);
  }
  .chip.solid-ok {
    color: var(--ok);
    border-color: color-mix(in oklch, var(--ok) 50%, var(--border));
  }
  .chip.solid-paper {
    color: var(--paper);
    border-color: color-mix(in oklch, var(--paper) 50%, var(--border));
  }

  /* —— KPI block —— */
  .kpi-num {
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-variant-numeric: tabular-nums;
    font-feature-settings: "tnum", "zero";
    font-weight: 500;
    letter-spacing: -0.01em;
  }

  /* —— sparkline —— */
  .spark path { fill: none; stroke-width: 1.25; }

  /* —— table —— */
  table.data { width: 100%; border-collapse: collapse; font-size: 12px; }
  table.data th {
    text-align: left;
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-size: 10px;
    letter-spacing: 0.10em;
    text-transform: uppercase;
    color: var(--text-dim);
    font-weight: 500;
    padding: 8px 10px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  table.data td {
    padding: 9px 10px;
    border-bottom: 1px solid var(--border);
    color: var(--text);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  table.data tr:last-child td { border-bottom: 0; }
  table.data tr.row-hover:hover { background: var(--panel-2); }

  /* —— input —— */
  .input {
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 6px 9px;
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-size: 12px;
  }
  .input:focus { outline: 1px solid var(--accent); }

  /* —— button —— */
  .btn {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 6px 11px;
    border: 1px solid var(--border-strong);
    background: var(--panel-2);
    color: var(--text);
    font-family: "IBM Plex Mono", ui-monospace, monospace;
    font-size: 11px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    cursor: pointer;
    transition: border-color .15s, background .15s, color .15s;
  }
  .btn:hover { border-color: var(--accent); color: var(--accent); }
  .btn.danger:hover { border-color: var(--block); color: var(--block); }
  .btn.primary {
    background: var(--accent);
    border-color: var(--accent);
    color: #1A1300;
  }
  .btn.primary:hover { filter: brightness(1.1); }
  .btn[disabled] { opacity: 0.4; cursor: not-allowed; }
  .btn[disabled]:hover { border-color: var(--border-strong); color: var(--text); }

  /* —— focus —— */
  :focus-visible { outline: 1px solid var(--accent); outline-offset: 1px; }

  /* —— layout root —— */
  .app {
    display: grid;
    grid-template-columns: 224px 1fr;
    grid-template-rows: auto auto 1fr;
    min-height: 100vh;
  }

  /* —— marquee LIVE BLOCKED strip —— */
  .blocked-strip {
    background: var(--bg);
    border-bottom: 1px solid var(--border);
    height: 26px;
    overflow: hidden;
    position: relative;
    grid-column: 1 / -1;
  }
  .blocked-strip-inner {
    height: 100%;
    background-image: repeating-linear-gradient(
      135deg,
      var(--hatch-strong) 0 10px,
      transparent 10px 20px
    );
    display: flex;
    align-items: center;
    gap: 24px;
    padding: 0 16px;
  }
  .blocked-marquee {
    display: inline-flex;
    gap: 36px;
    animation: marquee 60s linear infinite;
    white-space: nowrap;
  }
  @keyframes marquee {
    0% { transform: translateX(0); }
    100% { transform: translateX(-50%); }
  }

  /* —— text-edit cursor on titles —— */
  h1, h2, h3, h4 { margin: 0; font-weight: 500; }
</style>

<script type="application/json" id="theme-default">{"theme":"dark"}</script>
</head>
<body>
  <div id="root"></div>

  <script type="text/babel" src="tweaks-panel.jsx"></script>
  <script type="text/babel" src="data.jsx"></script>
  <script type="text/babel" src="primitives.jsx"></script>
  <script type="text/babel" src="mission-control.jsx"></script>
  <script type="text/babel" src="signal-explainability.jsx"></script>
  <script type="text/babel" src="risk-control.jsx"></script>
  <script type="text/babel" src="pages-operate.jsx"></script>
  <script type="text/babel" src="pages-inspect.jsx"></script>
  <script type="text/babel" src="pages-admin.jsx"></script>
  <script type="text/babel" src="pages-ai.jsx"></script>
  <script type="text/babel" src="pages-system.jsx"></script>
  <script type="text/babel" src="module-placeholder.jsx"></script>
  <script type="text/babel" src="app.jsx"></script>
</body>
</html>
===== END FILE: index.html =====

===== FILE: app.jsx =====
// Top-level app shell: sidebar nav + top bar + page router.

const { NAV } = window.AIBOT;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "dark"
}/*EDITMODE-END*/;

function App() {
  const [page, setPage] = React.useState("mission-control");
  const [tweaks, setTweak] = window.useTweaks
    ? window.useTweaks(TWEAK_DEFAULTS)
    : [TWEAK_DEFAULTS, () => {}];
  const theme = tweaks.theme || "dark";

  React.useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const pageLabel = React.useMemo(() => {
    for (const sec of NAV) for (const it of sec.items) if (it.id === page) return it.label;
    return "Module";
  }, [page]);

  const Body = (() => {
    const w = window;
    if (page === "mission-control")       return <MissionControl />;
    if (page === "signal-explainability") return <SignalExplainability />;
    if (page === "risk-control")          return <RiskControl />;
    if (page === "signals"            && w.SignalsPage)            return <w.SignalsPage />;
    if (page === "executions"         && w.ExecutionsPage)         return <w.ExecutionsPage />;
    if (page === "positions"          && w.PositionsPage)          return <w.PositionsPage />;
    if (page === "symbols"            && w.SymbolsPage)            return <w.SymbolsPage />;
    if (page === "paper-trading"      && w.PaperTradingPage)       return <w.PaperTradingPage />;
    if (page === "replay"             && w.ReplayPage)             return <w.ReplayPage />;
    if (page === "trainer-monitor"    && w.TrainerMonitorPage)     return <w.TrainerMonitorPage />;
    if (page === "coverage-atlas"     && w.CoverageAtlasPage)      return <w.CoverageAtlasPage />;
    if (page === "script-registry"    && w.ScriptRegistryPage)     return <w.ScriptRegistryPage />;
    if (page === "monitor-center"     && w.MonitorCenterPage)      return <w.MonitorCenterPage />;
    if (page === "audit-ledger"       && w.AuditLedgerPage)        return <w.AuditLedgerPage />;
    if (page === "live-readiness"     && w.LiveReadinessPage)      return <w.LiveReadinessPage />;
    if (page === "config-admin"       && w.ConfigAdminPage)        return <w.ConfigAdminPage />;
    if (page === "strategy-admin"     && w.StrategyAdminPage)      return <w.StrategyAdminPage />;
    if (page === "trainer-admin"      && w.TrainerAdminPage)       return <w.TrainerAdminPage />;
    if (page === "orchestrator-admin" && w.OrchestratorAdminPage)  return <w.OrchestratorAdminPage />;
    if (page === "execution-admin"    && w.ExecutionAdminPage)     return <w.ExecutionAdminPage />;
    if (page === "claude-admin"       && w.ClaudeAdminPage)        return <w.ClaudeAdminPage />;
    if (page === "ollama"             && w.OllamaPage)             return <w.OllamaPage />;
    if (page === "codex"              && w.CodexPage)              return <w.CodexPage />;
    if (page === "system-health"      && w.SystemHealthPage)       return <w.SystemHealthPage />;
    if (page === "build-validation"   && w.BuildValidationPage)    return <w.BuildValidationPage />;
    if (page === "mobile-readiness"   && w.MobileReadinessPage)    return <w.MobileReadinessPage />;
    return <ModulePlaceholder id={page} label={pageLabel} />;
  })();

  return (
    <div className="app">
      <BlockedStrip />
      <Sidebar page={page} setPage={setPage} />
      <TopBar pageLabel={pageLabel} />
      <main className="grid-bg" style={{ gridColumn: "2", padding: 18, minWidth: 0 }}>
        {Body}
      </main>
      {window.TweaksPanel && (
        <window.TweaksPanel title="Tweaks">
          <window.TweakSection title="Theme">
            <window.TweakRadio
              label="Mode"
              value={theme}
              onChange={v => setTweak("theme", v)}
              options={[
                { label: "Dark", value: "dark" },
                { label: "Light", value: "light" },
                { label: "Term.", value: "terminal" },
              ]}
            />
          </window.TweakSection>
        </window.TweaksPanel>
      )}
    </div>
  );
}

function BlockedStrip() {
  const msgs = [
    "LIVE TRADING · BLOCKED",
    "policy rev 18",
    "9 / 14 live-readiness items pending",
    "kill switch · ARMED",
    "operator approval required for any dangerous control",
    "audit chain · 1,204,481 links · 0 breaks",
    "redis ns · aibotv2:*",
    "paper mode · replay adapter v2",
  ];
  const run = (<span style={{ display: "inline-flex", gap: 36 }}>
    {msgs.concat(msgs).map((m, i) => (
      <span key={i} className="mono" style={{ fontSize: 10.5, letterSpacing: "0.10em", textTransform: "uppercase", color: "var(--accent)" }}>
        <span style={{ color: "var(--block)", marginRight: 8 }}>■</span>{m}
      </span>
    ))}
  </span>);
  return (
    <div className="blocked-strip">
      <div className="blocked-strip-inner">
        <div className="blocked-marquee">{run}</div>
      </div>
    </div>
  );
}

function Sidebar({ page, setPage }) {
  return (
    <aside style={{
      gridColumn: "1", gridRow: "2 / span 2",
      background: "var(--surface)",
      borderRight: "1px solid var(--border)",
      padding: "14px 0 18px",
      position: "sticky", top: 0, alignSelf: "start",
      height: "calc(100vh - 26px)",
      overflowY: "auto",
    }}>
      <div style={{ padding: "0 16px 14px", display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{
          width: 22, height: 22, border: "1px solid var(--accent)",
          display: "grid", placeItems: "center",
          fontFamily: "IBM Plex Mono, monospace", fontSize: 11, color: "var(--accent)",
        }}>◢</div>
        <div>
          <div className="cond" style={{ fontSize: 14, letterSpacing: "0.04em", lineHeight: 1 }}>AI BOT · V2</div>
          <div className="mono" style={{ fontSize: 9, color: "var(--text-dim)", letterSpacing: "0.10em", marginTop: 3 }}>CONTROL PLANE · 0.0.1</div>
        </div>
      </div>
      <div className="hr" />

      {NAV.map(sec => (
        <div key={sec.section} style={{ padding: "10px 0 6px" }}>
          <div className="label-mono" style={{ padding: "4px 16px 6px", color: "var(--text-faint)" }}>
            // {sec.section}
          </div>
          {sec.items.map(it => {
            const active = page === it.id;
            return (
              <button
                key={it.id}
                onClick={() => setPage(it.id)}
                style={{
                  display: "flex", alignItems: "center", gap: 9,
                  width: "100%",
                  padding: "5px 14px 5px 16px",
                  textAlign: "left",
                  borderLeft: `2px solid ${active ? "var(--accent)" : "transparent"}`,
                  background: active ? "color-mix(in oklch, var(--accent) 6%, transparent)" : "transparent",
                  color: active ? "var(--text)" : "var(--text-mid)",
                  fontSize: 12.5,
                  lineHeight: 1.3,
                  transition: "background .12s, color .12s",
                }}
              >
                <StatusDot status={it.status === "dim" ? "" : it.status} />
                <span style={{ flex: 1 }}>{it.label}</span>
                {it.count && (
                  <span className="mono" style={{
                    fontSize: 10, color: it.status === "warn" ? "var(--accent)" : it.status === "block" ? "var(--block)" : "var(--text-dim)",
                    minWidth: 18, textAlign: "right",
                  }}>{it.count}</span>
                )}
              </button>
            );
          })}
        </div>
      ))}

      <div className="hr" style={{ margin: "8px 0" }} />
      <div style={{ padding: "0 16px", display: "grid", gap: 6 }}>
        <div className="mono" style={{ fontSize: 10, color: "var(--text-dim)", display: "flex", justifyContent: "space-between" }}>
          <span>redis</span><span style={{ color: "var(--ok)" }}>● ok</span>
        </div>
        <div className="mono" style={{ fontSize: 10, color: "var(--text-dim)", display: "flex", justifyContent: "space-between" }}>
          <span>postgres</span><span style={{ color: "var(--ok)" }}>● ok</span>
        </div>
        <div className="mono" style={{ fontSize: 10, color: "var(--text-dim)", display: "flex", justifyContent: "space-between" }}>
          <span>trainer ipc</span><span style={{ color: "var(--ok)" }}>● ok</span>
        </div>
        <div className="mono" style={{ fontSize: 10, color: "var(--text-dim)", display: "flex", justifyContent: "space-between" }}>
          <span>live api</span><span style={{ color: "var(--block)" }}>● blocked</span>
        </div>
      </div>
    </aside>
  );
}

function TopBar({ pageLabel }) {
  const clock = useClock();
  const tick = useTicker(1000);
  const latency = 0.42 + ((tick * 13) % 17) / 100;
  return (
    <header style={{
      gridColumn: "2", gridRow: "2",
      display: "flex", alignItems: "center", gap: 14,
      padding: "10px 18px",
      borderBottom: "1px solid var(--border)",
      background: "var(--surface)",
      position: "sticky", top: 0, zIndex: 5,
    }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <span className="label-mono" style={{ color: "var(--text-faint)" }}>//</span>
        <span className="cond" style={{ fontSize: 17, letterSpacing: "0.02em" }}>{pageLabel}</span>
      </div>

      <div style={{ flex: 1 }} />

      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <Telemetry label="orch latency" value={`${latency.toFixed(2)}ms`} tone="ok" />
        <Telemetry label="gate latency" value="0.84ms" tone="ok" />
        <Telemetry label="redis ops/s" value={`${(9.4 + (tick % 5) * 0.1).toFixed(1)}`} tone="ok" />
        <span style={{ height: 16, width: 1, background: "var(--border)" }} />
        <Chip kind="paper">MODE · PAPER</Chip>
        <Chip kind="block">LIVE · BLOCKED</Chip>
        <span style={{ height: 16, width: 1, background: "var(--border)" }} />
        <div className="mono" style={{ fontSize: 11, color: "var(--text-mid)", textAlign: "right" }}>
          <div>{fmtClock(clock)}</div>
          <div style={{ color: "var(--text-dim)", fontSize: 10 }}>{fmtDate(clock)} · op wali1984</div>
        </div>
      </div>
    </header>
  );
}

function Telemetry({ label, value, tone }) {
  const c = tone === "ok" ? "var(--ok)" : tone === "warn" ? "var(--accent)" : tone === "block" ? "var(--block)" : "var(--text)";
  return (
    <div className="mono" style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span style={{ fontSize: 10, color: "var(--text-dim)", letterSpacing: "0.08em", textTransform: "uppercase" }}>{label}</span>
      <span style={{ fontSize: 12, color: c, fontVariantNumeric: "tabular-nums" }}>{value}</span>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
===== END FILE: app.jsx =====

===== FILE: data.jsx =====
// Static data + small helpers for the AI BOT V2 mockup.
// All numbers are illustrative; system is in PAPER mode, LIVE BLOCKED.

const NAV = [
  {
    section: "Operate",
    items: [
      { id: "mission-control",       label: "Mission Control",     status: "ok"    },
      { id: "signals",               label: "Signals",             status: "ok",   count: 47 },
      { id: "executions",            label: "Executions",          status: "ok"    },
      { id: "positions",             label: "Positions",           status: "ok",   count: 6 },
      { id: "symbols",               label: "Symbols",             status: "ok"    },
      { id: "paper-trading",         label: "Paper Trading",       status: "paper" },
      { id: "replay",                label: "Replay",              status: "dim"   },
    ],
  },
  {
    section: "Inspect",
    items: [
      { id: "signal-explainability", label: "Signal Explainability", status: "ok"   },
      { id: "trainer-monitor",       label: "Trainer Monitor",       status: "warn", count: 2 },
      { id: "coverage-atlas",        label: "Coverage / Atlas",      status: "ok"   },
      { id: "script-registry",       label: "Script Registry",       status: "warn", count: 11 },
      { id: "monitor-center",        label: "Monitor Center",        status: "ok"   },
      { id: "audit-ledger",          label: "Audit Ledger",          status: "ok"   },
    ],
  },
  {
    section: "Admin",
    items: [
      { id: "risk-control",          label: "Risk Control",          status: "block" },
      { id: "live-readiness",        label: "Live Readiness",        status: "block" },
      { id: "config-admin",          label: "Config Admin",          status: "ok"    },
      { id: "strategy-admin",        label: "Strategy Admin",        status: "ok"    },
      { id: "trainer-admin",         label: "Trainer Admin",         status: "ok"    },
      { id: "orchestrator-admin",    label: "Orchestrator Admin",    status: "ok"    },
      { id: "execution-admin",       label: "Execution Admin",       status: "ok"    },
    ],
  },
  {
    section: "AI Layer",
    items: [
      { id: "claude-admin",          label: "Claude Admin",          status: "ok"   },
      { id: "ollama",                label: "Ollama Local",          status: "ok"   },
      { id: "codex",                 label: "Codex Review",          status: "warn", count: 3 },
    ],
  },
  {
    section: "System",
    items: [
      { id: "system-health",         label: "System Health",         status: "ok"  },
      { id: "build-validation",      label: "Build / Validation",    status: "warn", count: 4 },
      { id: "mobile-readiness",      label: "Mobile Readiness",      status: "dim" },
    ],
  },
];

const SUBSYSTEMS = [
  { id: "trainer",      label: "Trainer",       status: "ok",    metric: "loss 0.0382",     detail: "step 184,201 · ckpt 0291",       last: "00:00:01.4" },
  { id: "orchestrator", label: "Orchestrator",  status: "ok",    metric: "throughput 9.4/s", detail: "queue 0 · 0 stuck",              last: "00:00:00.7" },
  { id: "risk-gateway", label: "Risk Gateway",  status: "block", metric: "live: BLOCKED",   detail: "12 rules armed · 0 overrides",   last: "00:00:00.3" },
  { id: "execution",   label: "Execution",      status: "paper", metric: "PAPER · 0 live",  detail: "adapter: replay-v2",             last: "00:00:01.1" },
  { id: "redis",        label: "Redis (v2)",   status: "ok",    metric: "ns aibotv2:*",     detail: "keys 12,481 · evicted 0",        last: "00:00:00.2" },
  { id: "postgres",     label: "Postgres",     status: "ok",    metric: "lag 0ms",         detail: "audit chain ok · 24h rows 1.2M", last: "00:00:00.8" },
];

const RISK_RULES = [
  { id: "live-trading",        label: "live trading enabled",        verdict: "BLOCKED",  reason: "operator approval required",                   level: "high"   },
  { id: "missing-attribution", label: "missing attribution",         verdict: "ARMED",    reason: "all signals must carry model_id + version",     level: "med"   },
  { id: "missing-signal-id",   label: "missing signal_id",           verdict: "ARMED",    reason: "uuidv7 required",                                level: "med"   },
  { id: "missing-confidence",  label: "missing confidence",          verdict: "ARMED",    reason: "calibrated [0..1] required",                     level: "med"   },
  { id: "stale-risk-add",      label: "stale risk-add signal",        verdict: "ARMED",    reason: "tick age > 2.5s rejects",                        level: "med"   },
  { id: "cross-margin",        label: "CROSS margin in live",         verdict: "BLOCKED",  reason: "ISOLATED only until live readiness review",      level: "high"  },
  { id: "leverage-cap",        label: "leverage above cap",           verdict: "ARMED",    reason: "cap 3x (paper) / 1x (live)",                     level: "med"   },
  { id: "duplicate-order-id",  label: "duplicate exchange_order_id",  verdict: "ARMED",    reason: "dedup window 24h",                               level: "med"   },
  { id: "missing-stop",        label: "missing stop policy",          verdict: "ARMED",    reason: "every signal must declare stop class",           level: "high"  },
  { id: "kill-switch-off",     label: "kill switch disabled",         verdict: "BLOCKED",  reason: "kill switch may not be disabled by automation",  level: "high"  },
  { id: "adjust-leverage",     label: "ADJUST_LEVERAGE",              verdict: "BLOCKED",  reason: "explicit human flag required",                   level: "high"  },
  { id: "hedge-dca",           label: "hedge / DCA enabled",          verdict: "ARMED",    reason: "deferred to strategy admin",                     level: "med"   },
];

const SIGNALS = [
  { id: "01HW9F2Z", t: "13:42:11.804", sym: "BTC-USDT", side: "LONG",  model: "hybrid-v4.2-ckpt0291", conf: 0.812, feat: "fresh 0.41s", stop: "ATR-2.4",  verdict: "ALLOW",  pnl: "+0.34%" },
  { id: "01HW9F2P", t: "13:42:09.181", sym: "ETH-USDT", side: "SHORT", model: "hybrid-v4.2-ckpt0291", conf: 0.704, feat: "fresh 0.62s", stop: "ATR-2.0",  verdict: "ALLOW",  pnl: "+0.11%" },
  { id: "01HW9F2D", t: "13:42:04.022", sym: "SOL-USDT", side: "LONG",  model: "hybrid-v4.2-ckpt0291", conf: 0.591, feat: "stale 3.1s",  stop: "ATR-2.6",  verdict: "BLOCK",  pnl: "—"      },
  { id: "01HW9F1Y", t: "13:42:01.475", sym: "AVAX-USDT",side: "LONG",  model: "hybrid-v4.2-ckpt0291", conf: 0.838, feat: "fresh 0.39s", stop: "ATR-2.2",  verdict: "ALLOW",  pnl: "+0.62%" },
  { id: "01HW9F1J", t: "13:41:58.901", sym: "BNB-USDT", side: "SHORT", model: "hybrid-v4.2-ckpt0291", conf: 0.523, feat: "fresh 0.51s", stop: "—",         verdict: "BLOCK",  pnl: "—"      },
  { id: "01HW9F18", t: "13:41:55.221", sym: "MATIC-USDT",side:"LONG",  model: "hybrid-v4.2-ckpt0291", conf: 0.776, feat: "fresh 0.44s", stop: "ATR-2.0",  verdict: "ALLOW",  pnl: "-0.08%" },
  { id: "01HW9F0V", t: "13:41:50.012", sym: "ARB-USDT", side: "LONG",  model: "hybrid-v4.2-ckpt0291", conf: 0.660, feat: "fresh 0.71s", stop: "ATR-2.6",  verdict: "ALLOW",  pnl: "+0.24%" },
  { id: "01HW9F0E", t: "13:41:45.811", sym: "DOGE-USDT",side: "SHORT", model: "hybrid-v4.2-ckpt0291", conf: 0.741, feat: "fresh 0.55s", stop: "ATR-1.8",  verdict: "ALLOW",  pnl: "+0.19%" },
];

const POSITIONS = [
  { sym: "BTC-USDT",  side: "L", qty: "0.0420",  entry: "60,418.10", mark: "60,612.45", upnl: "+8.16",  upnlPct: "+0.32%", age: "11m"   },
  { sym: "ETH-USDT",  side: "S", qty: "0.6100",  entry: "2,944.20",  mark: "2,935.81",  upnl: "+5.12",  upnlPct: "+0.28%", age: "07m"   },
  { sym: "AVAX-USDT", side: "L", qty: "12.000",  entry: "29.81",     mark: "30.02",     upnl: "+2.52",  upnlPct: "+0.70%", age: "04m"   },
  { sym: "SOL-USDT",  side: "L", qty: "1.4400",  entry: "138.92",    mark: "138.41",    upnl: "-0.73",  upnlPct: "-0.36%", age: "19m"   },
  { sym: "MATIC-USDT",side: "L", qty: "210.00",  entry: "0.6841",    mark: "0.6829",    upnl: "-0.25",  upnlPct: "-0.17%", age: "02m"   },
  { sym: "ARB-USDT",  side: "L", qty: "180.00",  entry: "0.9120",    mark: "0.9142",    upnl: "+0.40",  upnlPct: "+0.24%", age: "01m"   },
];

const AUDIT = [
  { seq: "1,204,481", t: "13:42:11.804", actor: "orchestrator", action: "signal.publish",        target: "01HW9F2Z", prev: "f2c4…91ae", curr: "a017…23dd", verdict: "ok" },
  { seq: "1,204,480", t: "13:42:11.804", actor: "risk-gateway", action: "gate.allow",            target: "01HW9F2Z", prev: "b8d1…77c0", curr: "f2c4…91ae", verdict: "ok" },
  { seq: "1,204,479", t: "13:42:11.802", actor: "trainer",      action: "prediction.publish",    target: "BTC-USDT", prev: "44ee…ae21", curr: "b8d1…77c0", verdict: "ok" },
  { seq: "1,204,478", t: "13:42:09.181", actor: "risk-gateway", action: "gate.allow",            target: "01HW9F2P", prev: "31ba…b7c4", curr: "44ee…ae21", verdict: "ok" },
  { seq: "1,204,477", t: "13:42:04.022", actor: "risk-gateway", action: "gate.block",            target: "01HW9F2D", prev: "00aa…1e7f", curr: "31ba…b7c4", verdict: "block" },
  { seq: "1,204,476", t: "13:42:01.475", actor: "execution",   action: "paper.fill",            target: "01HW9F1Y", prev: "9d72…5b8a", curr: "00aa…1e7f", verdict: "ok" },
  { seq: "1,204,475", t: "13:41:58.901", actor: "risk-gateway", action: "gate.block",            target: "01HW9F1J", prev: "5cef…83b1", curr: "9d72…5b8a", verdict: "block" },
  { seq: "1,204,474", t: "13:41:50.220", actor: "operator",     action: "config.update",         target: "leverage_cap_paper=3x", prev: "1100…aaff", curr: "5cef…83b1", verdict: "ok" },
];

const BUILD = [
  { id: "B-001", label: "scaffold.validation",       status: "PASS",  detail: "B_SCAFFOLD_VALIDATION.md verified · 14:02"  },
  { id: "B-002", label: "trainer.atlas.coverage",     status: "PASS",  detail: "Tier A: 31/31 sections raw-reviewed"        },
  { id: "B-003", label: "redis.namespace.isolation",  status: "PASS",  detail: "aibotv2:* only · 0 legacy writes detected" },
  { id: "B-004", label: "risk.gate.contract",        status: "WARN",  detail: "ADJUST_LEVERAGE path lacks raw evidence"   },
  { id: "B-005", label: "audit.chain.integrity",      status: "PASS",  detail: "1,204,481 links · 0 breaks"                 },
  { id: "B-006", label: "ollama.summary.verify",      status: "WARN",  detail: "3 packets pending Claude verification"      },
  { id: "B-007", label: "codex.review.gates",        status: "WARN",  detail: "milestone C review queued"                  },
  { id: "B-008", label: "live.readiness.checklist",  status: "WARN",  detail: "9 of 14 items unverified — see Live Ready." },
];

const TRAINER_PRED = [
  { sym: "BTC-USDT",  acc: 0.612, mae: 0.0021, brier: 0.184, drift: 0.04, last: "0.4s" },
  { sym: "ETH-USDT",  acc: 0.589, mae: 0.0030, brier: 0.198, drift: 0.07, last: "0.6s" },
  { sym: "SOL-USDT",  acc: 0.554, mae: 0.0048, brier: 0.214, drift: 0.18, last: "3.1s" },
  { sym: "AVAX-USDT", acc: 0.601, mae: 0.0034, brier: 0.191, drift: 0.05, last: "0.4s" },
  { sym: "BNB-USDT",  acc: 0.572, mae: 0.0029, brier: 0.205, drift: 0.09, last: "0.5s" },
  { sym: "MATIC-USDT",acc: 0.566, mae: 0.0041, brier: 0.211, drift: 0.11, last: "0.5s" },
];

// Equity curve seed (deterministic-ish ramp).
function makeEquityPath(width, height, points = 64) {
  // Start at 100k, end ~104.1k with realistic noise
  let v = 100000;
  const ys = [];
  const rng = (s => () => (s = (s * 9301 + 49297) % 233280) / 233280)(7);
  for (let i = 0; i < points; i++) {
    const drift = 65;            // slight up drift
    const noise = (rng() - 0.45) * 320;
    v += drift + noise;
    ys.push(v);
  }
  const min = Math.min(...ys), max = Math.max(...ys);
  const xs = ys.map((_, i) => (i / (points - 1)) * width);
  const yps = ys.map(y => height - ((y - min) / (max - min)) * height);
  const d  = xs.map((x, i) => `${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${yps[i].toFixed(2)}`).join(" ");
  const da = `${d} L ${width} ${height} L 0 ${height} Z`;
  return { d, da, min, max, last: ys[ys.length - 1], first: ys[0], ys };
}

// Tiny sparkline path
function makeSpark(seed, width = 64, height = 18, points = 24) {
  const rng = (s => () => (s = (s * 9301 + 49297) % 233280) / 233280)(seed);
  const ys = Array.from({ length: points }, () => rng());
  const min = Math.min(...ys), max = Math.max(...ys);
  const d = ys.map((y, i) => {
    const x = (i / (points - 1)) * width;
    const yy = height - ((y - min) / (max - min || 1)) * height;
    return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${yy.toFixed(2)}`;
  }).join(" ");
  return d;
}

window.AIBOT = {
  NAV, SUBSYSTEMS, RISK_RULES, SIGNALS, POSITIONS, AUDIT, BUILD, TRAINER_PRED,
  makeEquityPath, makeSpark,
};
===== END FILE: data.jsx =====

===== FILE: primitives.jsx =====
// Shared small primitives.

const { useEffect, useState, useRef, useMemo } = React;

function StatusDot({ status = "ok", pulse = false, size = 6 }) {
  const cls = `dot ${status}` + (pulse ? " pulse" : "");
  return <span className={cls} style={{ width: size, height: size }} />;
}

function Chip({ children, kind, style }) {
  const cls = "chip" + (kind ? ` solid-${kind}` : "");
  return <span className={cls} style={style}>{children}</span>;
}

function Panel({ title, right, children, bracketed = false, style, bodyStyle, noPad = false }) {
  return (
    <div className={"panel" + (bracketed ? " bracketed" : "")} style={style}>
      {bracketed && <><span className="br-bl" /><span className="br-br" /></>}
      {title && (
        <div className="panel-head">
          <div className="panel-title">{title}</div>
          {right}
        </div>
      )}
      <div className="panel-body" style={{ padding: noPad ? 0 : undefined, ...(bodyStyle || {}) }}>
        {children}
      </div>
    </div>
  );
}

function Eyebrow({ children, style }) {
  return <div className="eyebrow" style={style}>{children}</div>;
}

// useClock — wall clock that ticks every second
function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

// useTicker — return a number that flips every `ms` ms, with seed
function useTicker(ms = 1500) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), ms);
    return () => clearInterval(id);
  }, [ms]);
  return tick;
}

function fmtClock(d) {
  const pad = n => String(n).padStart(2, "0");
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC`;
}

function fmtDate(d) {
  const pad = n => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())}`;
}

Object.assign(window, { StatusDot, Chip, Panel, Eyebrow, useClock, useTicker, fmtClock, fmtDate });
===== END FILE: primitives.jsx =====

===== FILE: mission-control.jsx =====
// Mission Control — the operator's home page.

const { SUBSYSTEMS, SIGNALS, POSITIONS, AUDIT, BUILD, TRAINER_PRED, makeEquityPath, makeSpark } = window.AIBOT;

function MissionControl() {
  const tick = useTicker(1400);
  const eq = useMemo(() => makeEquityPath(720, 160, 96), []);

  // simulated live PnL — flips slightly each tick
  const livePnL = useMemo(() => {
    const base = 4112.42;
    const wiggle = ((tick * 137) % 73) / 10 - 3.65;
    return base + wiggle;
  }, [tick]);

  // signal feed shifts top entry
  const feedHead = useMemo(() => {
    const seedIdx = tick % SIGNALS.length;
    return [...SIGNALS.slice(seedIdx), ...SIGNALS.slice(0, seedIdx)];
  }, [tick]);

  return (
    <div data-screen-label="01 Mission Control">
      <MCHero pnl={livePnL} />

      <SubsystemRow />

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.55fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <EquityPanel eq={eq} pnl={livePnL} />
        <RiskGatePanel />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.4fr) minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <SignalStreamPanel signals={feedHead} tick={tick} />
        <PositionsPanel />
        <AuditChainPanel />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.2fr) minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <TrainerMonitorPanel />
        <AgentHealthPanel />
        <BuildValidationPanel />
      </div>
    </div>
  );
}

function MCHero({ pnl }) {
  const clock = useClock();
  return (
    <div className="panel bracketed hatch" style={{ position: "relative", padding: 0, marginBottom: 16 }}>
      <span className="br-bl" /><span className="br-br" />
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.7fr) repeat(4, minmax(0,1fr))", gap: 0 }}>
        <div style={{ padding: "20px 22px 20px", borderRight: "1px solid var(--border)" }}>
          <Eyebrow>// AI BOT V2 · control plane · session ░░░░-0291-z</Eyebrow>
          <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginTop: 8 }}>
            <h1 className="cond" style={{ fontSize: 36, lineHeight: 1, letterSpacing: "-0.01em" }}>
              MISSION CONTROL
            </h1>
            <Chip kind="block">LIVE TRADING · BLOCKED</Chip>
          </div>
          <div className="mono" style={{ marginTop: 12, color: "var(--text-mid)", fontSize: 12 }}>
            paper mode · replay adapter v2 · operator <span style={{ color: "var(--text)" }}>wali1984</span> · {fmtDate(clock)} {fmtClock(clock)}
          </div>
        </div>
        <HeroStat label="paper equity"   value="$104,112.42"     sub="+4.11% session"    tone="ok" />
        <HeroStat label="open positions" value="6"                sub="3L · 3S · 0 stuck" tone="text" />
        <HeroStat label="signals · 24h"  value="1,847"            sub="1,422 allow · 425 block" tone="text" />
        <HeroStat label="kill switch"    value="ARMED"            sub="trip-latency 0.2s" tone="warn" border={false} />
      </div>
    </div>
  );
}

function HeroStat({ label, value, sub, tone = "text", border = true }) {
  const color = tone === "ok" ? "var(--ok)" : tone === "warn" ? "var(--accent)" : tone === "block" ? "var(--block)" : "var(--text)";
  return (
    <div style={{ padding: "20px 18px", borderRight: border ? "1px solid var(--border)" : 0, background: "var(--panel)" }}>
      <div className="label-mono">{label}</div>
      <div className="kpi-num" style={{ fontSize: 26, marginTop: 6, color, lineHeight: 1 }}>{value}</div>
      <div className="mono" style={{ marginTop: 6, fontSize: 11, color: "var(--text-dim)" }}>{sub}</div>
    </div>
  );
}

function SubsystemRow() {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(6, minmax(0,1fr))", gap: 12 }}>
      {SUBSYSTEMS.map(s => (
        <div key={s.id} className="panel" style={{ padding: "11px 13px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div className="label-mono" style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <StatusDot status={s.status} pulse={s.status === "ok"} />
              {s.label}
            </div>
            <span className="mono" style={{ fontSize: 10, color: "var(--text-dim)" }}>{s.last}</span>
          </div>
          <div className="kpi-num" style={{
            fontSize: 14, marginTop: 8,
            color: s.status === "block" ? "var(--block)" : s.status === "paper" ? "var(--paper)" : s.status === "warn" ? "var(--accent)" : "var(--text)",
          }}>
            {s.metric}
          </div>
          <div className="mono" style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 4 }}>{s.detail}</div>
        </div>
      ))}
    </div>
  );
}

function EquityPanel({ eq, pnl }) {
  const W = 720, H = 180;
  return (
    <Panel
      title="// paper equity · session"
      right={
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span className="label-mono" style={{ color: "var(--text-dim)" }}>since 09:30 UTC</span>
          <Chip>1H</Chip>
          <Chip kind="warn">SESSION</Chip>
          <Chip>24H</Chip>
          <Chip>7D</Chip>
        </div>
      }
      bodyStyle={{ padding: 0 }}
    >
      <div style={{ display: "grid", gridTemplateColumns: "240px 1fr" }}>
        <div style={{ padding: 18, borderRight: "1px solid var(--border)" }}>
          <Eyebrow>equity (paper)</Eyebrow>
          <div className="kpi-num" style={{ fontSize: 32, marginTop: 4, lineHeight: 1 }}>$104,112<span style={{ color: "var(--text-mid)", fontSize: 22 }}>.42</span></div>
          <div className="mono" style={{ marginTop: 4, fontSize: 11, color: "var(--ok)" }}>+$4,112.42 · +4.11%</div>

          <div style={{ marginTop: 22 }}>
            <Eyebrow>realized · session</Eyebrow>
            <div className="kpi-num" style={{ fontSize: 18, marginTop: 2, color: "var(--ok)" }}>+$3,098.10</div>
          </div>
          <div style={{ marginTop: 14 }}>
            <Eyebrow>unrealized</Eyebrow>
            <div className="kpi-num" style={{ fontSize: 18, marginTop: 2, color: "var(--ok)" }}>+$1,014.32</div>
          </div>
          <div style={{ marginTop: 14 }}>
            <Eyebrow>max drawdown · 7d</Eyebrow>
            <div className="kpi-num" style={{ fontSize: 18, marginTop: 2, color: "var(--block)" }}>−2.74%</div>
          </div>
        </div>
        <div style={{ position: "relative", padding: "14px 18px 18px" }}>
          <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" style={{ display: "block" }}>
            <defs>
              <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"  stopColor="var(--ok)" stopOpacity="0.18" />
                <stop offset="100%" stopColor="var(--ok)" stopOpacity="0" />
              </linearGradient>
              <pattern id="eqGrid" width="60" height="40" patternUnits="userSpaceOnUse">
                <path d="M 60 0 L 0 0 0 40" fill="none" stroke="var(--grid-line)" strokeWidth="1" />
              </pattern>
            </defs>
            <rect width={W} height={H} fill="url(#eqGrid)" />
            {[0.25, 0.5, 0.75].map(p => (
              <line key={p} x1="0" x2={W} y1={H * p} y2={H * p} stroke="var(--border)" strokeDasharray="2 3" opacity="0.6" />
            ))}
            <path d={eq.da} fill="url(#eqGrad)" />
            <path d={eq.d}  stroke="var(--ok)" strokeWidth="1.4" fill="none" />
            {/* live cursor */}
            <line x1={W - 0.5} x2={W - 0.5} y1="0" y2={H} stroke="var(--accent)" strokeDasharray="2 2" opacity="0.6" />
            <circle cx={W - 2} cy={(H * 0.18).toFixed(2)} r="3" fill="var(--accent)" />
          </svg>
          <div style={{ position: "absolute", top: 16, right: 22, textAlign: "right" }} className="mono">
            <div style={{ fontSize: 10, color: "var(--text-dim)" }}>SHARPE / SORTINO</div>
            <div className="kpi-num" style={{ fontSize: 14, color: "var(--text)" }}>1.84 / 2.41</div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginTop: 8 }}>
            <MiniStat label="trades" value="247" />
            <MiniStat label="win-rate" value="61.4%" tone="ok" />
            <MiniStat label="avg R" value="0.78" />
            <MiniStat label="best/worst" value="+1.92 / −1.41" />
          </div>
        </div>
      </div>
    </Panel>
  );
}

function MiniStat({ label, value, tone }) {
  const c = tone === "ok" ? "var(--ok)" : tone === "block" ? "var(--block)" : "var(--text)";
  return (
    <div>
      <div className="label-mono">{label}</div>
      <div className="kpi-num" style={{ fontSize: 14, color: c }}>{value}</div>
    </div>
  );
}

function RiskGatePanel() {
  const allow = 1422, block = 425, stale = 11;
  const total = allow + block + stale;
  const ap = (allow / total) * 100, bp = (block / total) * 100, sp = (stale / total) * 100;
  return (
    <Panel title="// risk gateway · 24h"
      right={<Chip kind="warn">12 RULES ARMED</Chip>}
    >
      <div style={{ display: "flex", height: 10, border: "1px solid var(--border)", overflow: "hidden" }}>
        <div style={{ width: `${ap}%`, background: "var(--ok)" }} />
        <div style={{ width: `${bp}%`, background: "var(--block)" }} className="hatch-strong" />
        <div style={{ width: `${sp}%`, background: "var(--warn)" }} />
      </div>
      <div className="mono" style={{ display: "flex", justifyContent: "space-between", marginTop: 6, fontSize: 11, color: "var(--text-mid)" }}>
        <span><StatusDot status="ok" /> allow <span style={{ color: "var(--text)" }}>{allow}</span></span>
        <span><StatusDot status="block" /> block <span style={{ color: "var(--text)" }}>{block}</span></span>
        <span><StatusDot status="warn" /> stale <span style={{ color: "var(--text)" }}>{stale}</span></span>
      </div>

      <div style={{ marginTop: 16 }}>
        <Eyebrow>top blocks · last 24h</Eyebrow>
        <div style={{ marginTop: 8 }}>
          {[
            { rule: "stale-risk-add", c: 142, sym: "feature tick > 2.5s" },
            { rule: "missing-stop",   c: 96,  sym: "no stop class" },
            { rule: "leverage-cap",   c: 71,  sym: "leverage > 3x" },
            { rule: "duplicate-order-id", c: 64, sym: "dedup window 24h" },
            { rule: "missing-confidence", c: 38, sym: "calibration null" },
            { rule: "cross-margin",   c: 14,  sym: "CROSS in paper-live" },
          ].map(r => (
            <div key={r.rule} style={{ display: "grid", gridTemplateColumns: "150px 1fr 40px", gap: 10, alignItems: "center", padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
              <span className="mono" style={{ fontSize: 11, color: "var(--text)" }}>{r.rule}</span>
              <span className="mono" style={{ fontSize: 10.5, color: "var(--text-dim)" }}>{r.sym}</span>
              <span className="kpi-num" style={{ fontSize: 12, textAlign: "right", color: "var(--block)" }}>{r.c}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="hatch" style={{ marginTop: 14, padding: "10px 12px", border: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10 }}>
        <StatusDot status="block" pulse />
        <span className="mono" style={{ fontSize: 11 }}>
          <span style={{ color: "var(--block)", fontWeight: 600 }}>LIVE ENABLE</span>
          <span style={{ color: "var(--text-mid)" }}> · requires </span>
          <span style={{ color: "var(--text)" }}>2-operator approval · 9/14 readiness items pending</span>
        </span>
      </div>
    </Panel>
  );
}

function SignalStreamPanel({ signals, tick }) {
  return (
    <Panel title="// signal stream"
      right={
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <StatusDot status="ok" pulse />
          <span className="label-mono">{47 + (tick % 4)} / min</span>
          <span style={{ color: "var(--text-faint)" }}>·</span>
          <span className="label-mono">model hybrid-v4.2-ckpt0291</span>
        </div>
      }
      bodyStyle={{ padding: 0 }}
    >
      <table className="data">
        <thead>
          <tr>
            <th style={{ width: 70 }}>time</th>
            <th style={{ width: 80 }}>signal_id</th>
            <th>symbol</th>
            <th>side</th>
            <th>conf</th>
            <th>features</th>
            <th>stop</th>
            <th>gate</th>
            <th style={{ textAlign: "right" }}>pnl</th>
          </tr>
        </thead>
        <tbody>
          {signals.slice(0, 8).map((s, i) => (
            <tr key={s.id + i} className="row-hover" style={{ background: i === 0 ? "color-mix(in oklch, var(--accent) 6%, transparent)" : "transparent" }}>
              <td className="mono" style={{ color: "var(--text-dim)", fontSize: 11 }}>{s.t.slice(0, 8)}</td>
              <td className="mono" style={{ color: "var(--text)" }}>{s.id}</td>
              <td className="mono" style={{ color: "var(--text)" }}>{s.sym}</td>
              <td className="mono" style={{ color: s.side === "LONG" ? "var(--ok)" : "var(--block)", fontWeight: 600 }}>{s.side}</td>
              <td><ConfBar v={s.conf} /></td>
              <td className="mono" style={{ color: s.feat.startsWith("stale") ? "var(--accent)" : "var(--text-mid)", fontSize: 11 }}>{s.feat}</td>
              <td className="mono" style={{ color: s.stop === "—" ? "var(--block)" : "var(--text-mid)", fontSize: 11 }}>{s.stop}</td>
              <td>
                <Chip kind={s.verdict === "ALLOW" ? "ok" : "block"} style={{ padding: "1px 6px" }}>
                  {s.verdict}
                </Chip>
              </td>
              <td className="mono" style={{ textAlign: "right", color: s.pnl.startsWith("+") ? "var(--ok)" : s.pnl.startsWith("-") ? "var(--block)" : "var(--text-dim)" }}>{s.pnl}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function ConfBar({ v }) {
  const pct = Math.round(v * 100);
  const tone = v >= 0.70 ? "var(--ok)" : v >= 0.60 ? "var(--accent)" : "var(--block)";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 80 }}>
      <div style={{ width: 50, height: 6, background: "var(--bg)", border: "1px solid var(--border)" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: tone }} />
      </div>
      <span className="mono" style={{ fontSize: 11, color: "var(--text)", width: 28 }}>{v.toFixed(2)}</span>
    </div>
  );
}

function PositionsPanel() {
  return (
    <Panel title="// positions (paper)"
      right={<span className="label-mono">6 open · 0 stuck</span>}
      bodyStyle={{ padding: 0 }}
    >
      <table className="data">
        <thead>
          <tr>
            <th>sym</th><th>s</th><th>qty</th><th>mark</th><th style={{ textAlign: "right" }}>upnl</th>
          </tr>
        </thead>
        <tbody>
          {POSITIONS.map(p => (
            <tr key={p.sym} className="row-hover">
              <td className="mono" style={{ color: "var(--text)" }}>{p.sym}</td>
              <td className="mono" style={{ color: p.side === "L" ? "var(--ok)" : "var(--block)", fontWeight: 600 }}>{p.side}</td>
              <td className="mono" style={{ color: "var(--text-mid)" }}>{p.qty}</td>
              <td className="mono" style={{ color: "var(--text-mid)" }}>{p.mark}</td>
              <td className="mono" style={{ textAlign: "right", color: p.upnl.startsWith("+") ? "var(--ok)" : "var(--block)" }}>
                {p.upnl}<span style={{ color: "var(--text-dim)", marginLeft: 6 }}>{p.upnlPct}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function AuditChainPanel() {
  return (
    <Panel title="// audit ledger · tail"
      right={
        <span className="label-mono">
          <StatusDot status="ok" /> 1,204,481 links · 0 breaks
        </span>
      }
      bodyStyle={{ padding: 0 }}
    >
      <div>
        {AUDIT.slice(0, 7).map((a, i) => (
          <div key={a.seq} style={{
            display: "grid",
            gridTemplateColumns: "10px 60px 1fr 70px",
            gap: 8,
            alignItems: "center",
            padding: "7px 12px",
            borderBottom: i === AUDIT.length - 1 ? 0 : "1px solid var(--border)",
          }}>
            <StatusDot status={a.verdict === "ok" ? "ok" : "block"} />
            <span className="mono" style={{ fontSize: 10, color: "var(--text-dim)" }}>{a.t.slice(0,8)}</span>
            <div style={{ minWidth: 0 }}>
              <div className="mono" style={{ fontSize: 11, color: "var(--text)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                <span style={{ color: "var(--accent)" }}>{a.actor}</span>
                <span style={{ color: "var(--text-dim)" }}> · </span>
                {a.action}
              </div>
              <div className="mono" style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {a.target}
              </div>
            </div>
            <span className="mono" style={{ fontSize: 10, color: "var(--text-faint)", textAlign: "right" }}>{a.curr}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function TrainerMonitorPanel() {
  return (
    <Panel
      title="// trainer · prediction monitor"
      right={
        <span className="label-mono">
          <StatusDot status="ok" pulse /> hybrid-v4.2 · ckpt 0291 · step 184,201
        </span>
      }
      bodyStyle={{ padding: 0 }}
    >
      <table className="data">
        <thead>
          <tr>
            <th>symbol</th><th>acc</th><th>mae</th><th>brier</th><th>drift</th><th style={{ textAlign: "right" }}>last</th>
          </tr>
        </thead>
        <tbody>
          {TRAINER_PRED.map(t => (
            <tr key={t.sym} className="row-hover">
              <td className="mono">{t.sym}</td>
              <td className="mono"><BarCell v={t.acc} max={0.7} tone={t.acc >= 0.59 ? "var(--ok)" : "var(--accent)"} /></td>
              <td className="mono">{t.mae.toFixed(4)}</td>
              <td className="mono">{t.brier.toFixed(3)}</td>
              <td className="mono" style={{ color: t.drift > 0.15 ? "var(--accent)" : "var(--text-mid)" }}>
                {t.drift.toFixed(2)}
              </td>
              <td className="mono" style={{ textAlign: "right", color: t.last.startsWith("3") ? "var(--accent)" : "var(--text-dim)" }}>{t.last}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function BarCell({ v, max = 1, tone = "var(--text)" }) {
  const pct = Math.min(100, (v / max) * 100);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 80 }}>
      <div style={{ width: 44, height: 4, background: "var(--bg)", border: "1px solid var(--border)" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: tone }} />
      </div>
      <span className="mono" style={{ fontSize: 11, color: "var(--text)", width: 32 }}>{v.toFixed(3)}</span>
    </div>
  );
}

function AgentHealthPanel() {
  const agents = [
    { name: "Claude (max 5x)",  status: "ok",   detail: "/usage 38% · session bounded",       spark: 11 },
    { name: "Ollama (local)",    status: "ok",   detail: "qwen2.5:14b · 23 packets queued",    spark: 22 },
    { name: "Codex review",      status: "warn", detail: "milestone C queued · 3 gates open",  spark: 33 },
  ];
  return (
    <Panel title="// ai supervision · health" right={<Chip>3 layers</Chip>}>
      <div style={{ display: "grid", gap: 10 }}>
        {agents.map(a => (
          <div key={a.name} style={{ padding: "10px 12px", border: "1px solid var(--border)", background: "var(--panel-2)" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <StatusDot status={a.status} pulse={a.status === "ok"} />
                <span className="mono" style={{ fontSize: 12, color: "var(--text)" }}>{a.name}</span>
              </span>
              <svg width="64" height="18" className="spark"><path d={makeSpark(a.spark)} stroke={a.status === "warn" ? "var(--accent)" : "var(--ok)"} /></svg>
            </div>
            <div className="mono" style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 6 }}>{a.detail}</div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 12, padding: "8px 10px", border: "1px dashed var(--border-strong)", display: "flex", justifyContent: "space-between" }}>
        <span className="label-mono">evidence integrity</span>
        <span className="mono" style={{ fontSize: 11 }}>
          <span style={{ color: "var(--ok)" }}>raw-verified 412</span>
          <span style={{ color: "var(--text-dim)" }}> · </span>
          <span style={{ color: "var(--accent)" }}>unverified 14</span>
        </span>
      </div>
    </Panel>
  );
}

function BuildValidationPanel() {
  return (
    <Panel title="// build · validation status"
      right={<Chip kind="warn">4 warn · 0 fail</Chip>}
    >
      <div>
        {BUILD.map(b => (
          <div key={b.id} style={{
            display: "grid",
            gridTemplateColumns: "44px 1fr 56px",
            gap: 10,
            alignItems: "center",
            padding: "7px 0",
            borderBottom: "1px solid var(--border)",
          }}>
            <span className="mono" style={{ fontSize: 10, color: "var(--text-dim)" }}>{b.id}</span>
            <div style={{ minWidth: 0 }}>
              <div className="mono" style={{ fontSize: 11.5, color: "var(--text)" }}>{b.label}</div>
              <div className="mono" style={{ fontSize: 10.5, color: "var(--text-dim)", marginTop: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{b.detail}</div>
            </div>
            <span style={{ textAlign: "right" }}>
              <Chip kind={b.status === "PASS" ? "ok" : b.status === "WARN" ? "warn" : "block"}>{b.status}</Chip>
            </span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

window.MissionControl = MissionControl;
===== END FILE: mission-control.jsx =====

===== FILE: signal-explainability.jsx =====
// Signal Explainability — single-signal deep dive.

function SignalExplainability() {
  const sig = {
    id: "01HW9F2Z-T7-K3B1-Q-XS21",
    t:   "2026-05-10T13:42:11.804Z",
    sym: "BTC-USDT",
    side: "LONG",
    conf: 0.812,
    calibrated: 0.787,
    model: "hybrid-v4.2",
    ckpt: "0291",
    step: "184,201",
    feature_age_ms: 412,
    stop_class: "ATR-2.4",
    verdict: "ALLOW",
    orch_reason: "regime=trend-bull · book-imbalance=0.61 · funding=−0.0012",
  };
  return (
    <div data-screen-label="08 Signal Explainability">
      <div className="panel bracketed" style={{ marginBottom: 16, padding: "18px 22px" }}>
        <span className="br-bl" /><span className="br-br" />
        <Eyebrow>// signal · explainability · raw evidence pinned</Eyebrow>
        <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginTop: 8, flexWrap: "wrap" }}>
          <h1 className="cond" style={{ fontSize: 30 }}>{sig.sym} · {sig.side}</h1>
          <span className="mono" style={{ fontSize: 12, color: "var(--text-mid)" }}>{sig.id}</span>
          <Chip kind="ok">GATE · ALLOW</Chip>
          <Chip kind="paper">PAPER-FILLED · +0.34%</Chip>
        </div>
        <div className="mono" style={{ marginTop: 10, fontSize: 12, color: "var(--text-dim)" }}>
          published {sig.t} · model {sig.model} · ckpt {sig.ckpt} · step {sig.step}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr) minmax(0,1fr)", gap: 16 }}>
        <Panel title="// model output">
          <KV k="raw output (logits)" v="[ +1.412, −0.703, +0.089 ]" />
          <KV k="softmax"             v="[ 0.812, 0.118, 0.070 ]" />
          <KV k="argmax"              v="LONG" tone="ok" />
          <KV k="confidence (raw)"    v="0.812" />
          <KV k="confidence (calib)"  v="0.787" />
          <KV k="calibration"         v="platt-v3 · brier 0.184" />
          <KV k="model_id"            v="hybrid-v4.2-ckpt0291" mono />
          <KV k="prediction sha"      v="b8d1c1c4d8c0…77c0" mono dim />
        </Panel>

        <Panel title="// feature snapshot">
          {[
            { k: "price.last",       v: "60,418.10",  age: "0.12s", fresh: true },
            { k: "book.imbalance",   v: "+0.61",     age: "0.18s", fresh: true },
            { k: "vol.5m",           v: "1,820.4",   age: "0.30s", fresh: true },
            { k: "funding.next",     v: "−0.0012",   age: "0.40s", fresh: true },
            { k: "regime.label",     v: "trend-bull", age: "0.41s", fresh: true },
            { k: "macd.hist",        v: "+0.0028",   age: "0.42s", fresh: true },
            { k: "atr.14",          v: "182.41",    age: "0.42s", fresh: true },
            { k: "depth.5bp",        v: "12.4 / 11.1", age: "1.41s", fresh: true },
            { k: "social.sent.30m",  v: "0.42",      age: "2.81s", fresh: false },
          ].map(f => (
            <div key={f.k} style={{
              display: "grid", gridTemplateColumns: "1fr auto auto",
              gap: 10, alignItems: "center",
              padding: "6px 0", borderBottom: "1px solid var(--border)",
            }}>
              <span className="mono" style={{ fontSize: 11.5, color: "var(--text)" }}>{f.k}</span>
              <span className="mono" style={{ fontSize: 11.5, color: "var(--text-mid)" }}>{f.v}</span>
              <span className="mono" style={{ fontSize: 10.5, color: f.fresh ? "var(--text-dim)" : "var(--accent)" }}>
                {f.fresh ? "fresh" : "stale"} {f.age}
              </span>
            </div>
          ))}
        </Panel>

        <Panel title="// risk gateway · verdict trace">
          <div style={{ display: "grid", gap: 6 }}>
            {[
              { rule: "attribution.present",   pass: true,  note: "model_id + version present" },
              { rule: "signal_id.present",     pass: true,  note: "uuidv7 valid" },
              { rule: "confidence.calibrated", pass: true,  note: "platt-v3 0.787 ∈ [0,1]" },
              { rule: "feature.freshness",     pass: true,  note: "max age 412ms < 2500ms" },
              { rule: "stop.class.present",    pass: true,  note: "ATR-2.4" },
              { rule: "margin.mode",           pass: true,  note: "ISOLATED · CROSS only in live" },
              { rule: "leverage.cap",          pass: true,  note: "1.5x ≤ 3x (paper cap)" },
              { rule: "dedup.order_id",        pass: true,  note: "0 collisions · 24h window" },
              { rule: "kill.switch.armed",     pass: true,  note: "armed" },
              { rule: "live.enabled",          pass: true,  note: "n/a · paper mode" },
            ].map(r => (
              <div key={r.rule} style={{ display: "grid", gridTemplateColumns: "10px 1fr auto", gap: 10, alignItems: "center", padding: "4px 0" }}>
                <StatusDot status={r.pass ? "ok" : "block"} />
                <div>
                  <div className="mono" style={{ fontSize: 11.5, color: "var(--text)" }}>{r.rule}</div>
                  <div className="mono" style={{ fontSize: 10.5, color: "var(--text-dim)" }}>{r.note}</div>
                </div>
                <span className="mono" style={{ fontSize: 10, color: r.pass ? "var(--ok)" : "var(--block)" }}>{r.pass ? "PASS" : "FAIL"}</span>
              </div>
            ))}
          </div>
          <div className="hatch" style={{ marginTop: 12, padding: "8px 10px", border: "1px solid var(--border)" }}>
            <span className="mono" style={{ fontSize: 11, color: "var(--text)" }}>
              <span style={{ color: "var(--ok)", fontWeight: 600 }}>VERDICT: ALLOW</span>
              <span style={{ color: "var(--text-dim)" }}> · gate latency 0.84ms · gateway rev a7c1b3</span>
            </span>
          </div>
        </Panel>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.4fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// raw evidence pointers · lineage">
          <table className="data">
            <thead><tr><th>artefact</th><th>pointer</th><th>verify</th></tr></thead>
            <tbody>
              {[
                { a: "redis · prediction event", p: "aibotv2:pred:BTC-USDT:184201",            v: "XRANGE aibotv2:pred:BTC-USDT 184201-0 184201-0" },
                { a: "redis · signal event",     p: "aibotv2:sig:01HW9F2Z",                    v: "GET aibotv2:sig:01HW9F2Z" },
                { a: "postgres · audit row",     p: "audit_chain · seq 1,204,481",             v: "SELECT * FROM audit_chain WHERE seq=1204481" },
                { a: "source · risk_gateway.py", p: "v2/backend/risk/gateway.py L142-L188",    v: "git blob 2f1c…aa9 · sha-256 c7…b1" },
                { a: "source · publish.py",      p: "v2/backend/orchestrator/publish.py L91", v: "git blob 8d10…44a · sha-256 31…d2" },
                { a: "checkpoint · 0291",        p: "trainer/ckpt/0291.pt",                    v: "sha-256 7e…fb · size 412 MB" },
                { a: "config · risk.yaml",       p: "v2/config/risk.yaml @ rev 18",            v: "diff rev17→rev18 · 2 lines" },
              ].map(r => (
                <tr key={r.a} className="row-hover">
                  <td className="mono" style={{ color: "var(--text)" }}>{r.a}</td>
                  <td className="mono" style={{ color: "var(--text-mid)" }}>{r.p}</td>
                  <td className="mono" style={{ color: "var(--text-dim)", fontSize: 11 }}>{r.v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title="// orchestrator reasoning">
          <div className="mono" style={{ fontSize: 12, color: "var(--text-mid)", lineHeight: 1.7 }}>
            <span style={{ color: "var(--accent)" }}>regime</span> = <span style={{ color: "var(--text)" }}>trend-bull</span><br/>
            <span style={{ color: "var(--accent)" }}>book.imbalance</span> = <span style={{ color: "var(--text)" }}>+0.61</span><br/>
            <span style={{ color: "var(--accent)" }}>funding.next</span> = <span style={{ color: "var(--text)" }}>−0.0012</span><br/>
            <span style={{ color: "var(--accent)" }}>vol.regime</span> = <span style={{ color: "var(--text)" }}>med · σ-band 2</span><br/>
            <br/>
            <span style={{ color: "var(--text-dim)" }}>→ strategy <span style={{ color: "var(--text)" }}>mass-momentum-v3</span> elected</span><br/>
            <span style={{ color: "var(--text-dim)" }}>→ size <span style={{ color: "var(--text)" }}>0.042 BTC</span> · risk <span style={{ color: "var(--text)" }}>0.18% equity</span></span><br/>
            <span style={{ color: "var(--text-dim)" }}>→ stop <span style={{ color: "var(--text)" }}>ATR-2.4 · 60,000.18</span></span><br/>
            <span style={{ color: "var(--text-dim)" }}>→ target <span style={{ color: "var(--text)" }}>0.78R</span> · trail after 0.5R</span><br/>
          </div>
          <div className="hr" style={{ margin: "14px 0" }} />
          <Eyebrow>missing evidence</Eyebrow>
          <div className="mono" style={{ fontSize: 11, color: "var(--text)", marginTop: 6 }}>
            <span style={{ color: "var(--accent)" }}>·</span> social.sent.30m at 2.81s — within tolerance but flagged for next gate review.
          </div>
        </Panel>
      </div>
    </div>
  );
}

function KV({ k, v, tone, mono, dim }) {
  const c = tone === "ok" ? "var(--ok)" : tone === "block" ? "var(--block)" : dim ? "var(--text-dim)" : "var(--text)";
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 10, padding: "6px 0", borderBottom: "1px solid var(--border)" }}>
      <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>{k}</span>
      <span className={mono ? "mono" : "mono"} style={{ fontSize: 12, color: c, textAlign: "right" }}>{v}</span>
    </div>
  );
}

window.SignalExplainability = SignalExplainability;
===== END FILE: signal-explainability.jsx =====

===== FILE: risk-control.jsx =====
// Risk Control — gate rules, dangerous controls, kill switch.

const { RISK_RULES } = window.AIBOT;

function RiskControl() {
  const [killArmed, setKillArmed] = React.useState(true);
  return (
    <div data-screen-label="11 Risk Control">
      <div className="panel bracketed hatch" style={{ padding: "18px 22px", marginBottom: 16 }}>
        <span className="br-bl" /><span className="br-br" />
        <Eyebrow>// risk control · dangerous surface · 2-operator approval enforced</Eyebrow>
        <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginTop: 8 }}>
          <h1 className="cond" style={{ fontSize: 30 }}>RISK CONTROL</h1>
          <Chip kind="block">LIVE TRADING · BLOCKED</Chip>
          <Chip>policy rev 18 · sha c7e2…b1</Chip>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 320px", gap: 16 }}>
        <Panel title="// gate rules · 12 armed">
          <table className="data">
            <thead>
              <tr><th>rule</th><th>verdict</th><th>level</th><th>reason</th><th style={{ textAlign: "right" }}>action</th></tr>
            </thead>
            <tbody>
              {RISK_RULES.map(r => (
                <tr key={r.id} className="row-hover">
                  <td className="mono" style={{ color: "var(--text)" }}>{r.label}</td>
                  <td>
                    <Chip kind={r.verdict === "BLOCKED" ? "block" : "ok"}>
                      {r.verdict}
                    </Chip>
                  </td>
                  <td className="mono" style={{ fontSize: 11, color: r.level === "high" ? "var(--block)" : "var(--text-mid)" }}>
                    {r.level.toUpperCase()}
                  </td>
                  <td className="mono" style={{ color: "var(--text-dim)", fontSize: 11 }}>{r.reason}</td>
                  <td style={{ textAlign: "right" }}>
                    <button className="btn" disabled={r.level === "high"}>edit</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <div style={{ display: "grid", gap: 16, alignContent: "start" }}>
          <Panel title="// kill switch" bracketed>
            <div className="hatch" style={{ padding: "16px 14px", border: "1px solid var(--border)", textAlign: "center" }}>
              <Eyebrow>status</Eyebrow>
              <div className="cond" style={{ fontSize: 34, marginTop: 4, color: killArmed ? "var(--accent)" : "var(--block)" }}>
                {killArmed ? "ARMED" : "TRIPPED"}
              </div>
              <div className="mono" style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 4 }}>
                trip-latency 0.2s · cooldown 5m
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 14, justifyContent: "center" }}>
                <button className="btn danger" onClick={() => setKillArmed(false)}>TRIP NOW</button>
                <button className="btn" onClick={() => setKillArmed(true)}>RE-ARM</button>
              </div>
            </div>
            <div className="mono" style={{ fontSize: 10.5, color: "var(--text-dim)", marginTop: 12 }}>
              trip cancels open orders · halts orchestrator · sets execution to read-only · audit-logged.
            </div>
          </Panel>

          <Panel title="// dangerous controls">
            {[
              { k: "enable live trading",  v: "BLOCKED" },
              { k: "add live api keys",     v: "BLOCKED" },
              { k: "increase leverage",     v: "BLOCKED" },
              { k: "enable CROSS margin",  v: "BLOCKED" },
              { k: "increase position cap", v: "BLOCKED" },
              { k: "disable kill switch",  v: "BLOCKED" },
              { k: "ADJUST_LEVERAGE flag", v: "BLOCKED" },
              { k: "enable hedge / DCA",   v: "ARMED"  },
              { k: "switch paper→live",   v: "BLOCKED" },
            ].map(d => (
              <div key={d.k} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: "1px solid var(--border)", alignItems: "center" }}>
                <span className="mono" style={{ fontSize: 11.5, color: "var(--text)" }}>{d.k}</span>
                <Chip kind={d.v === "BLOCKED" ? "block" : "warn"}>{d.v}</Chip>
              </div>
            ))}
            <div className="mono" style={{ fontSize: 10.5, color: "var(--text-dim)", marginTop: 10, lineHeight: 1.5 }}>
              every action here is dual-approved · ledger-pinned · cooldown 60s after escalation.
            </div>
          </Panel>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// live readiness · 9 of 14 unverified">
          {[
            { k: "risk.gate.contract.raw-evidenced",     ok: true,  n: "src lines L142-L188 · audit row 1,204,402" },
            { k: "audit.chain.integrity.verified",        ok: true,  n: "1,204,481 links · 0 breaks" },
            { k: "redis.namespace.isolation.proven",      ok: true,  n: "aibotv2:* only · 0 legacy writes" },
            { k: "trainer.atlas.tier-A.complete",         ok: true,  n: "31/31 sections raw-reviewed" },
            { k: "kill.switch.physical-or-logical.tested", ok: true, n: "last drill 2026-05-08 13:02" },
            { k: "ADJUST_LEVERAGE.evidence.complete",     ok: false, n: "no raw exchange-action trace" },
            { k: "codex.review.milestone-C.signed-off",   ok: false, n: "queued · 3 review gates open" },
            { k: "operator.2-of-N.policy.bound",          ok: false, n: "policy defined · key ceremony pending" },
            { k: "live.api.keys.escrowed",               ok: false, n: "not configured · expected" },
            { k: "live.dry-run.drill",                     ok: false, n: "not scheduled" },
          ].map(r => (
            <div key={r.k} style={{ display: "grid", gridTemplateColumns: "10px 1fr auto", gap: 10, alignItems: "center", padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
              <StatusDot status={r.ok ? "ok" : "warn"} />
              <div>
                <div className="mono" style={{ fontSize: 11.5, color: "var(--text)" }}>{r.k}</div>
                <div className="mono" style={{ fontSize: 10.5, color: "var(--text-dim)" }}>{r.n}</div>
              </div>
              <Chip kind={r.ok ? "ok" : "warn"}>{r.ok ? "VERIFIED" : "PENDING"}</Chip>
            </div>
          ))}
        </Panel>

        <Panel title="// approval queue">
          {[
            { id: "AP-211", t: "enable hedge mode on BTC-USDT", req: "strategy-admin", needs: "2 / 2", got: "1 / 2", state: "AWAIT-2ND" },
            { id: "AP-210", t: "lift leverage cap to 3.5x (paper)", req: "operator", needs: "2 / 2", got: "0 / 2", state: "AWAIT-1ST" },
            { id: "AP-209", t: "rotate ollama model to llama3.1:8b", req: "ai-admin",  needs: "1 / 1", got: "1 / 1", state: "EXECUTING" },
            { id: "AP-208", t: "promote ckpt 0291 → 0292",          req: "trainer-admin", needs: "1 / 1", got: "0 / 1", state: "AWAIT-1ST" },
            { id: "AP-207", t: "purge stale signals > 48h",          req: "audit-admin", needs: "1 / 1", got: "1 / 1", state: "DONE" },
          ].map(a => (
            <div key={a.id} style={{ display: "grid", gridTemplateColumns: "60px 1fr 90px 90px", gap: 10, padding: "8px 0", borderBottom: "1px solid var(--border)", alignItems: "center" }}>
              <span className="mono" style={{ fontSize: 10, color: "var(--text-dim)" }}>{a.id}</span>
              <div>
                <div className="mono" style={{ fontSize: 12, color: "var(--text)" }}>{a.t}</div>
                <div className="mono" style={{ fontSize: 10.5, color: "var(--text-dim)", marginTop: 2 }}>req · {a.req} · approvals {a.got} of {a.needs}</div>
              </div>
              <span className="mono" style={{ fontSize: 10.5, color: "var(--text-mid)" }}>{a.state}</span>
              <span style={{ textAlign: "right" }}>
                <button className="btn" disabled={a.state === "DONE"}>review</button>
              </span>
            </div>
          ))}
        </Panel>
      </div>
    </div>
  );
}

window.RiskControl = RiskControl;
===== END FILE: risk-control.jsx =====

===== FILE: pages-operate.jsx =====
// Operate section pages: Signals, Executions, Positions, Symbols, Paper Trading, Replay

const { SIGNALS, POSITIONS, makeSpark } = window.AIBOT;

function PageHeader({ sub, title, chips, screen }) {
  return (
    <div className="panel bracketed" style={{ marginBottom: 16, padding: "18px 22px" }} data-screen-label={screen}>
      <span className="br-bl" /><span className="br-br" />
      <Eyebrow>// {sub}</Eyebrow>
      <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginTop: 8, flexWrap: "wrap" }}>
        <h1 className="cond" style={{ fontSize: 30 }}>{title}</h1>
        {chips}
      </div>
    </div>
  );
}
window.PageHeader = PageHeader;

function SignalsPage() {
  const SYMS = ["BTC-USDT","ETH-USDT","SOL-USDT","AVAX-USDT","BNB-USDT","MATIC-USDT","ARB-USDT","DOGE-USDT","LINK-USDT","ATOM-USDT"];
  const ROWS = Array.from({ length: 22 }, (_, i) => {
    const r = (s => (s = (s * 9301 + 49297) % 233280) / 233280)(i + 11);
    const sym = SYMS[i % SYMS.length];
    const side = i % 3 === 0 ? "SHORT" : "LONG";
    const conf = (0.51 + ((i * 73) % 41) / 100).toFixed(3);
    const verdict = i % 5 === 4 ? "BLOCK" : "ALLOW";
    const fresh = i % 7 === 5 ? "stale 2.9s" : `fresh ${(0.2 + (i % 7) * 0.1).toFixed(2)}s`;
    const stop = i % 11 === 0 ? "—" : `ATR-${(1.8 + (i % 5) * 0.2).toFixed(1)}`;
    return { id: `01HW9${String.fromCharCode(65 + (i % 26))}${(i*7).toString(36).toUpperCase().slice(0,3)}`,
      t: `13:42:${String(59 - i).padStart(2, "0")}.${String((i * 137) % 999).padStart(3, "0")}`,
      sym, side, conf: +conf, fresh, stop, verdict, pnl: verdict === "BLOCK" ? "—" : (i % 4 === 0 ? `-0.${(10 + i % 30).toString().padStart(2,"0")}%` : `+0.${(11 + i % 60).toString().padStart(2,"0")}%`)
    };
  });
  return (
    <div>
      <PageHeader screen="05 Signals" sub="published signals · v2 lineage chain · model hybrid-v4.2" title="SIGNALS"
        chips={<><Chip kind="ok">STREAM · LIVE</Chip><Chip>{ROWS.length} of 1,847 (24h)</Chip><Chip>1,422 allow · 425 block</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12, marginBottom: 16 }}>
        {[
          { l: "throughput", v: "47 / min", s: 11, t: "var(--ok)" },
          { l: "avg confidence", v: "0.704", s: 22, t: "var(--text)" },
          { l: "allow rate · 24h", v: "76.9%", s: 33, t: "var(--ok)" },
          { l: "feature stale · 1h", v: "11", s: 44, t: "var(--accent)" },
        ].map(k => (
          <div key={k.l} className="panel" style={{ padding: "12px 14px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span className="label-mono">{k.l}</span>
              <svg width="64" height="18" className="spark"><path d={makeSpark(k.s)} stroke={k.t} /></svg>
            </div>
            <div className="kpi-num" style={{ fontSize: 22, marginTop: 6, color: k.t }}>{k.v}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", gap: 10, marginBottom: 12, alignItems: "center", flexWrap: "wrap" }}>
        <input className="input mono" placeholder="filter signal_id, sym, model…" style={{ width: 320 }} />
        <Chip kind="warn">SIDE · ALL</Chip>
        <Chip>VERDICT · ALL</Chip>
        <Chip>SYMBOL · ALL</Chip>
        <Chip>MODEL · hybrid-v4.2-ckpt0291</Chip>
        <Chip>FRESH ≤ 2.5s</Chip>
        <span style={{ flex: 1 }} />
        <button className="btn">EXPORT.NDJSON</button>
        <button className="btn">REPLAY SELECTED</button>
      </div>

      <Panel title="// signal stream · 22 rows" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead>
            <tr><th>time</th><th>signal_id</th><th>symbol</th><th>side</th><th>conf</th><th>features</th><th>stop</th><th>gate</th><th style={{ textAlign: "right" }}>paper pnl</th></tr>
          </thead>
          <tbody>
            {ROWS.map(s => (
              <tr key={s.id} className="row-hover">
                <td className="mono" style={{ color: "var(--text-dim)" }}>{s.t}</td>
                <td className="mono">{s.id}</td>
                <td className="mono">{s.sym}</td>
                <td className="mono" style={{ color: s.side === "LONG" ? "var(--ok)" : "var(--block)", fontWeight: 600 }}>{s.side}</td>
                <td className="mono">
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <div style={{ width: 48, height: 5, background: "var(--bg)", border: "1px solid var(--border)" }}>
                      <div style={{ width: `${s.conf * 100}%`, height: "100%", background: s.conf >= 0.7 ? "var(--ok)" : s.conf >= 0.6 ? "var(--accent)" : "var(--block)" }} />
                    </div>
                    <span style={{ fontSize: 11 }}>{s.conf.toFixed(3)}</span>
                  </div>
                </td>
                <td className="mono" style={{ color: s.fresh.startsWith("stale") ? "var(--accent)" : "var(--text-mid)", fontSize: 11 }}>{s.fresh}</td>
                <td className="mono" style={{ color: s.stop === "—" ? "var(--block)" : "var(--text-mid)", fontSize: 11 }}>{s.stop}</td>
                <td><Chip kind={s.verdict === "ALLOW" ? "ok" : "block"}>{s.verdict}</Chip></td>
                <td className="mono" style={{ textAlign: "right", color: s.pnl.startsWith("+") ? "var(--ok)" : s.pnl.startsWith("-") ? "var(--block)" : "var(--text-dim)" }}>{s.pnl}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

function ExecutionsPage() {
  const ROWS = Array.from({ length: 16 }, (_, i) => {
    const SYMS = ["BTC-USDT","ETH-USDT","SOL-USDT","AVAX-USDT","ARB-USDT","BNB-USDT"];
    const sym = SYMS[i % SYMS.length];
    const side = i % 3 === 0 ? "SELL" : "BUY";
    return {
      id: `EX-${String(284100 - i).padStart(6, "0")}`,
      sig: `01HW9F${(i*3).toString(36).toUpperCase().slice(0,3)}`,
      t: `13:42:${String(58 - i).padStart(2,"0")}.${String((i*131)%999).padStart(3,"0")}`,
      sym, side,
      qty: ((0.04 + i * 0.011) % 2).toFixed(4),
      px: (60000 + i * 12.3).toFixed(2),
      slip: `${(i % 4 === 0 ? "+" : "-")}${(0.01 + (i % 7) * 0.003).toFixed(3)}bp`,
      lat: `${(0.4 + (i * 0.07) % 1.4).toFixed(2)}ms`,
      route: i % 5 === 4 ? "replay-v2" : "paper-direct",
      status: i % 9 === 8 ? "REJECT" : "FILL",
      fee: (0.0008 + (i * 0.0001) % 0.001).toFixed(5),
    };
  });
  return (
    <div>
      <PageHeader screen="06 Executions" sub="execution intents · paper mode · 0 live · audit-pinned" title="EXECUTIONS"
        chips={<><Chip kind="paper">ADAPTER · replay-v2</Chip><Chip kind="ok">FILL RATE 98.2%</Chip><Chip>247 today</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, minmax(0,1fr))", gap: 12, marginBottom: 16 }}>
        {[
          { l: "fills · 24h", v: "1,418", t: "var(--text)" },
          { l: "rejects · 24h", v: "23", t: "var(--block)" },
          { l: "avg slippage", v: "+0.74bp", t: "var(--accent)" },
          { l: "avg latency", v: "0.82ms", t: "var(--ok)" },
          { l: "fee total · 24h", v: "$148.21", t: "var(--text)" },
        ].map(k => (
          <div key={k.l} className="panel" style={{ padding: "12px 14px" }}>
            <span className="label-mono">{k.l}</span>
            <div className="kpi-num" style={{ fontSize: 20, marginTop: 6, color: k.t }}>{k.v}</div>
          </div>
        ))}
      </div>

      <Panel title="// execution intents · latest 16" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>id</th><th>signal</th><th>time</th><th>sym</th><th>side</th><th>qty</th><th>px</th><th>slip</th><th>latency</th><th>route</th><th>fee</th><th>status</th></tr></thead>
          <tbody>
            {ROWS.map(r => (
              <tr key={r.id} className="row-hover">
                <td className="mono">{r.id}</td>
                <td className="mono" style={{ color: "var(--accent)" }}>{r.sig}</td>
                <td className="mono" style={{ color: "var(--text-dim)" }}>{r.t}</td>
                <td className="mono">{r.sym}</td>
                <td className="mono" style={{ color: r.side === "BUY" ? "var(--ok)" : "var(--block)", fontWeight: 600 }}>{r.side}</td>
                <td className="mono">{r.qty}</td>
                <td className="mono">{r.px}</td>
                <td className="mono" style={{ color: r.slip.startsWith("+") ? "var(--accent)" : "var(--ok)" }}>{r.slip}</td>
                <td className="mono">{r.lat}</td>
                <td className="mono" style={{ color: "var(--text-mid)" }}>{r.route}</td>
                <td className="mono">${r.fee}</td>
                <td><Chip kind={r.status === "FILL" ? "ok" : "block"}>{r.status}</Chip></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// reject taxonomy · 24h">
          {[
            { r: "missing_stop_policy", c: 9 },
            { r: "feature_stale", c: 6 },
            { r: "duplicate_order_id", c: 4 },
            { r: "leverage_above_cap", c: 2 },
            { r: "cross_margin_in_live", c: 1 },
            { r: "missing_attribution", c: 1 },
          ].map(x => (
            <div key={x.r} style={{ display: "grid", gridTemplateColumns: "1fr 50px 40px", gap: 10, padding: "5px 0", borderBottom: "1px solid var(--border)", alignItems: "center" }}>
              <span className="mono" style={{ fontSize: 11.5 }}>{x.r}</span>
              <div style={{ height: 6, background: "var(--bg)", border: "1px solid var(--border)" }}>
                <div style={{ width: `${x.c * 10}%`, height: "100%", background: "var(--block)" }} className="hatch-strong" />
              </div>
              <span className="mono" style={{ textAlign: "right", color: "var(--block)" }}>{x.c}</span>
            </div>
          ))}
        </Panel>
        <Panel title="// latency distribution · gate→fill">
          <div style={{ display: "flex", alignItems: "flex-end", height: 120, gap: 4, padding: "12px 0" }}>
            {[12, 24, 38, 56, 71, 89, 64, 41, 27, 15, 8, 4, 2, 1].map((v, i) => (
              <div key={i} style={{ flex: 1, background: i < 6 ? "var(--ok)" : i < 11 ? "var(--accent)" : "var(--block)", height: `${v}%` }} />
            ))}
          </div>
          <div className="mono" style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--text-dim)", marginTop: 4 }}>
            <span>0.2ms</span><span>p50 0.82</span><span>p95 1.41</span><span>p99 2.18</span><span>3.0ms+</span>
          </div>
        </Panel>
      </div>
    </div>
  );
}

function PositionsPage() {
  return (
    <div>
      <PageHeader screen="07 Positions" sub="open positions · paper · cost basis · reconciled" title="POSITIONS"
        chips={<><Chip kind="paper">PAPER</Chip><Chip kind="ok">6 OPEN · 0 STUCK</Chip><Chip>UPNL +$15.22</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12, marginBottom: 16 }}>
        {[
          { l: "gross exposure", v: "$24,818", t: "var(--text)" },
          { l: "net exposure", v: "+$11,402", t: "var(--ok)" },
          { l: "margin used", v: "$3,941", t: "var(--text)" },
          { l: "free margin", v: "$96,170", t: "var(--ok)" },
        ].map(k => (
          <div key={k.l} className="panel" style={{ padding: "12px 14px" }}>
            <span className="label-mono">{k.l}</span>
            <div className="kpi-num" style={{ fontSize: 22, marginTop: 6, color: k.t }}>{k.v}</div>
          </div>
        ))}
      </div>

      <Panel title="// open positions" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>sym</th><th>side</th><th>qty</th><th>entry</th><th>mark</th><th>liq</th><th>upnl</th><th>roe</th><th>fees</th><th>opened</th><th>stop</th><th>tp</th><th></th></tr></thead>
          <tbody>
            {POSITIONS.map((p, i) => (
              <tr key={p.sym} className="row-hover">
                <td className="mono">{p.sym}</td>
                <td className="mono" style={{ color: p.side === "L" ? "var(--ok)" : "var(--block)", fontWeight: 600 }}>{p.side === "L" ? "LONG" : "SHORT"}</td>
                <td className="mono">{p.qty}</td>
                <td className="mono">{p.entry}</td>
                <td className="mono">{p.mark}</td>
                <td className="mono" style={{ color: "var(--text-dim)" }}>{(parseFloat(p.entry.replace(/,/g,"")) * (p.side === "L" ? 0.78 : 1.22)).toFixed(2)}</td>
                <td className="mono" style={{ color: p.upnl.startsWith("+") ? "var(--ok)" : "var(--block)" }}>{p.upnl}</td>
                <td className="mono" style={{ color: p.upnlPct.startsWith("+") ? "var(--ok)" : "var(--block)" }}>{p.upnlPct}</td>
                <td className="mono">${(0.18 + i * 0.04).toFixed(2)}</td>
                <td className="mono" style={{ color: "var(--text-dim)" }}>{p.age}</td>
                <td className="mono" style={{ color: "var(--accent)" }}>ATR-2.{i + 2}</td>
                <td className="mono">0.8R</td>
                <td><button className="btn danger">CLOSE</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.2fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// position lots · cost basis ledger">
          <table className="data">
            <thead><tr><th>sym</th><th>seq</th><th>added</th><th>qty</th><th>px</th><th>fees</th><th>realized</th></tr></thead>
            <tbody>
              {[
                ["BTC-USDT", "L-204", "13:31:11", "0.02", "60,401.10", "0.61", "—"],
                ["BTC-USDT", "L-203", "13:18:02", "0.022", "60,432.80", "0.66", "—"],
                ["ETH-USDT", "S-118", "13:35:42", "0.61", "2,944.20",  "0.45", "+5.12"],
                ["AVAX-USDT", "L-091", "13:38:51", "12.00", "29.81", "0.07", "—"],
                ["SOL-USDT", "L-322", "13:23:11", "1.44", "138.92",  "0.20", "—"],
                ["MATIC-USDT", "L-411", "13:40:21", "210.00", "0.6841", "0.07", "—"],
              ].map(r => (
                <tr key={r[1]} className="row-hover">{r.map((c, i) => <td key={i} className="mono" style={{ color: i === 6 && c.startsWith("+") ? "var(--ok)" : "var(--text)" }}>{c}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel title="// reconciliation · last sync 00:00:42">
          {[
            { k: "paper-ledger vs orchestrator", v: "MATCH", c: "ok" },
            { k: "ledger vs audit-chain", v: "MATCH", c: "ok" },
            { k: "redis pos-cache vs ledger", v: "MATCH", c: "ok" },
            { k: "fills vs lots", v: "MATCH", c: "ok" },
            { k: "fee total drift", v: "0.0001 USD", c: "ok" },
            { k: "subaccount split", v: "n/a · single", c: "" },
          ].map(r => (
            <div key={r.k} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: "1px solid var(--border)", alignItems: "center" }}>
              <span className="mono" style={{ fontSize: 11.5 }}>{r.k}</span>
              <span className="mono" style={{ fontSize: 11, color: r.c === "ok" ? "var(--ok)" : "var(--text-dim)" }}>{r.v}</span>
            </div>
          ))}
        </Panel>
      </div>
    </div>
  );
}

function SymbolsPage() {
  const ROWS = [
    { sym: "BTC-USDT", venue: "binance-spot", uni: "core", regime: "trend-bull", vol: "1,820.4", funding: "−0.0012", oi: "+2.1%", state: "ACTIVE", spark: 11 },
    { sym: "ETH-USDT", venue: "binance-spot", uni: "core", regime: "range",      vol: "1,108.7", funding: "−0.0009", oi: "+0.4%", state: "ACTIVE", spark: 12 },
    { sym: "SOL-USDT", venue: "binance-spot", uni: "core", regime: "trend-bull", vol: "412.0",   funding: "+0.0014", oi: "+5.1%", state: "ACTIVE", spark: 13 },
    { sym: "AVAX-USDT", venue: "binance-spot", uni: "core", regime: "trend-bull", vol: "188.4",  funding: "+0.0008", oi: "+3.1%", state: "ACTIVE", spark: 14 },
    { sym: "BNB-USDT",  venue: "binance-spot", uni: "core", regime: "range",     vol: "98.4",    funding: "−0.0001", oi: "−0.2%", state: "ACTIVE", spark: 15 },
    { sym: "MATIC-USDT",venue: "binance-spot", uni: "core", regime: "trend-bear", vol: "210.7", funding: "−0.0021", oi: "−1.4%", state: "ACTIVE", spark: 16 },
    { sym: "ARB-USDT",  venue: "binance-spot", uni: "core", regime: "trend-bull", vol: "188.4", funding: "+0.0008", oi: "+1.4%", state: "ACTIVE", spark: 17 },
    { sym: "DOGE-USDT", venue: "binance-spot", uni: "watch", regime: "range",    vol: "78.4",   funding: "+0.0001", oi: "+0.1%", state: "WATCH",  spark: 18 },
    { sym: "LINK-USDT", venue: "binance-spot", uni: "watch", regime: "trend-bull", vol: "61.2", funding: "+0.0006", oi: "+2.4%", state: "WATCH",  spark: 19 },
    { sym: "ATOM-USDT", venue: "binance-spot", uni: "watch", regime: "range",    vol: "44.1",   funding: "−0.0002", oi: "−0.1%", state: "PAUSED", spark: 20 },
    { sym: "XRP-USDT",  venue: "okx-spot",     uni: "exclude", regime: "—",      vol: "—",      funding: "—",       oi: "—",    state: "EXCLUDED", spark: 21 },
  ];
  return (
    <div>
      <PageHeader screen="08 Symbols" sub="symbol universe · regime · venue · core / watch / excluded" title="SYMBOLS"
        chips={<><Chip kind="ok">7 ACTIVE</Chip><Chip kind="warn">2 WATCH</Chip><Chip kind="block">1 EXCLUDED</Chip></>} />

      <div style={{ display: "flex", gap: 10, marginBottom: 12, alignItems: "center" }}>
        <input className="input" placeholder="search symbol…" style={{ width: 240 }} />
        <Chip>VENUE · all</Chip><Chip>REGIME · all</Chip><Chip>UNIVERSE · all</Chip>
        <span style={{ flex: 1 }} />
        <button className="btn">+ ADD SYMBOL</button>
      </div>

      <Panel title="// symbol universe" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>symbol</th><th>venue</th><th>universe</th><th>regime</th><th>vol·24h (M)</th><th>funding</th><th>oi Δ</th><th>price · 24h</th><th>state</th><th></th></tr></thead>
          <tbody>
            {ROWS.map(r => (
              <tr key={r.sym} className="row-hover">
                <td className="mono"><strong>{r.sym}</strong></td>
                <td className="mono" style={{ color: "var(--text-mid)" }}>{r.venue}</td>
                <td className="mono"><Chip>{r.uni}</Chip></td>
                <td className="mono" style={{ color: r.regime.includes("bull") ? "var(--ok)" : r.regime.includes("bear") ? "var(--block)" : "var(--text-mid)" }}>{r.regime}</td>
                <td className="mono">{r.vol}</td>
                <td className="mono" style={{ color: r.funding.startsWith("+") ? "var(--ok)" : r.funding.startsWith("−") ? "var(--block)" : "var(--text-dim)" }}>{r.funding}</td>
                <td className="mono" style={{ color: r.oi.startsWith("+") ? "var(--ok)" : r.oi.startsWith("−") ? "var(--block)" : "var(--text-dim)" }}>{r.oi}</td>
                <td><svg width="120" height="22" className="spark"><path d={makeSpark(r.spark, 120, 22, 32)} stroke={r.regime.includes("bull") ? "var(--ok)" : r.regime.includes("bear") ? "var(--block)" : "var(--text-mid)"} /></svg></td>
                <td><Chip kind={r.state === "ACTIVE" ? "ok" : r.state === "EXCLUDED" ? "block" : "warn"}>{r.state}</Chip></td>
                <td><button className="btn">edit</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

function PaperTradingPage() {
  const eq = window.AIBOT.makeEquityPath(900, 200, 128);
  return (
    <div>
      <PageHeader screen="09 Paper Trading" sub="paper loop · isolated · same lineage chain as live · ledger-pinned" title="PAPER TRADING"
        chips={<><Chip kind="paper">PAPER · MODE</Chip><Chip kind="ok">RUNNING · 11:42:08</Chip><Chip>$100,000 → $104,112</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,2fr) minmax(0,1fr)", gap: 16, marginBottom: 16 }}>
        <Panel title="// paper equity · 7-day window" bodyStyle={{ padding: 0 }}>
          <div style={{ padding: 16 }}>
            <svg viewBox={`0 0 900 200`} width="100%" height={200} preserveAspectRatio="none">
              <defs>
                <linearGradient id="pp-grad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--ok)" stopOpacity="0.18" /><stop offset="100%" stopColor="var(--ok)" stopOpacity="0" /></linearGradient>
              </defs>
              {[0.2, 0.4, 0.6, 0.8].map(p => <line key={p} x1="0" x2="900" y1={200 * p} y2={200 * p} stroke="var(--border)" strokeDasharray="2 3" />)}
              <path d={eq.da} fill="url(#pp-grad)" />
              <path d={eq.d} stroke="var(--ok)" fill="none" strokeWidth="1.4" />
            </svg>
          </div>
        </Panel>
        <Panel title="// session summary">
          {[
            { k: "starting equity", v: "$100,000.00", t: "var(--text)" },
            { k: "current equity",  v: "$104,112.42", t: "var(--ok)" },
            { k: "realized pnl",    v: "+$3,098.10",  t: "var(--ok)" },
            { k: "unrealized pnl",  v: "+$1,014.32",  t: "var(--ok)" },
            { k: "trades",          v: "247",         t: "var(--text)" },
            { k: "win rate",        v: "61.4%",       t: "var(--ok)" },
            { k: "avg R",           v: "0.78",        t: "var(--text)" },
            { k: "best trade",      v: "+1.92R",      t: "var(--ok)" },
            { k: "worst trade",     v: "−1.41R",      t: "var(--block)" },
            { k: "max drawdown",    v: "−2.74%",      t: "var(--block)" },
            { k: "sharpe / sortino", v: "1.84 / 2.41", t: "var(--text)" },
            { k: "kill switch",     v: "ARMED",       t: "var(--accent)" },
          ].map(r => (
            <div key={r.k} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
              <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>{r.k}</span>
              <span className="mono" style={{ fontSize: 12, color: r.t }}>{r.v}</span>
            </div>
          ))}
        </Panel>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16 }}>
        <Panel title="// closed trades · last 12" bodyStyle={{ padding: 0 }}>
          <table className="data">
            <thead><tr><th>t</th><th>sym</th><th>side</th><th>R</th><th>pnl</th><th>reason</th></tr></thead>
            <tbody>
              {[
                ["13:21","BTC-USDT","L","+1.21","+$182.30","tp"],
                ["13:18","ETH-USDT","S","+0.82","+$92.10","tp"],
                ["13:14","SOL-USDT","L","-0.41","-$31.40","stop"],
                ["13:09","AVAX-USDT","L","+1.92","+$408.21","tp"],
                ["13:01","DOGE-USDT","S","+0.27","+$11.40","trail"],
                ["12:54","MATIC-USDT","L","+0.64","+$68.10","tp"],
                ["12:48","BNB-USDT","S","-0.21","-$28.81","stop"],
                ["12:42","ARB-USDT","L","+0.81","+$54.10","tp"],
                ["12:38","LINK-USDT","L","+1.04","+$118.40","tp"],
                ["12:31","BTC-USDT","S","-1.41","-$211.18","stop"],
                ["12:22","ETH-USDT","L","+0.42","+$48.10","trail"],
                ["12:14","SOL-USDT","L","+0.78","+$84.41","tp"],
              ].map((r,i) => (
                <tr key={i}><td className="mono" style={{ color: "var(--text-dim)" }}>{r[0]}</td><td className="mono">{r[1]}</td><td className="mono" style={{ color: r[2] === "L" ? "var(--ok)" : "var(--block)" }}>{r[2]}</td><td className="mono" style={{ color: r[3].startsWith("+") ? "var(--ok)" : "var(--block)" }}>{r[3]}</td><td className="mono" style={{ color: r[4].startsWith("+") ? "var(--ok)" : "var(--block)" }}>{r[4]}</td><td className="mono" style={{ color: "var(--text-mid)" }}>{r[5]}</td></tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel title="// equity by strategy">
          {[
            { k: "mass-momentum-v3", v: "+$2,118.20", pct: 64, t: "var(--ok)" },
            { k: "mean-revert-v2", v: "+$612.40", pct: 18, t: "var(--ok)" },
            { k: "breakout-atr-v1", v: "+$382.10", pct: 11, t: "var(--ok)" },
            { k: "funding-skew-v1", v: "+$208.41", pct: 6, t: "var(--ok)" },
            { k: "regime-flip-v0", v: "−$222.91", pct: 7, t: "var(--block)" },
          ].map(s => (
            <div key={s.k} style={{ padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span className="mono" style={{ fontSize: 12 }}>{s.k}</span>
                <span className="mono" style={{ fontSize: 12, color: s.t }}>{s.v}</span>
              </div>
              <div style={{ marginTop: 5, height: 4, background: "var(--bg)", border: "1px solid var(--border)" }}>
                <div style={{ width: `${s.pct}%`, height: "100%", background: s.t }} />
              </div>
            </div>
          ))}
        </Panel>
      </div>
    </div>
  );
}

function ReplayPage() {
  return (
    <div>
      <PageHeader screen="10 Replay" sub="deterministic replay · stored market data · strategy versions · shared lineage" title="REPLAY"
        chips={<><Chip kind="paper">SANDBOX</Chip><Chip kind="ok">DETERMINISM · BYTE-IDENTICAL</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "320px minmax(0,1fr)", gap: 16 }}>
        <Panel title="// new replay run">
          <Eyebrow>strategy</Eyebrow>
          <select className="input" style={{ width: "100%", marginTop: 4 }}><option>mass-momentum-v3 · rev 41</option><option>mean-revert-v2 · rev 22</option><option>breakout-atr-v1 · rev 7</option></select>
          <Eyebrow style={{ marginTop: 14 }}>window</Eyebrow>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginTop: 4 }}>
            <input className="input" defaultValue="2026-04-12" />
            <input className="input" defaultValue="2026-05-09" />
          </div>
          <Eyebrow style={{ marginTop: 14 }}>symbols</Eyebrow>
          <div style={{ marginTop: 4, display: "flex", flexWrap: "wrap", gap: 4 }}>
            {["BTC","ETH","SOL","AVAX","BNB","ARB"].map(s => <Chip kind="warn" key={s}>{s}</Chip>)}
          </div>
          <Eyebrow style={{ marginTop: 14 }}>seed · feature cache</Eyebrow>
          <input className="input" defaultValue="0x4f1c…b09a" style={{ width: "100%", marginTop: 4 }} />
          <div style={{ display: "flex", gap: 6, marginTop: 16 }}>
            <button className="btn primary">START REPLAY</button>
            <button className="btn">SAVE CONFIG</button>
          </div>
        </Panel>

        <Panel title="// replay runs" bodyStyle={{ padding: 0 }}>
          <table className="data">
            <thead><tr><th>id</th><th>strategy</th><th>window</th><th>signals</th><th>fills</th><th>pnl</th><th>sharpe</th><th>dd</th><th>determinism</th><th>state</th></tr></thead>
            <tbody>
              {[
                { id: "RP-0118", s: "mass-momentum-v3 · 41", w: "2026-04-12 → 05-09", sg: 12842, fl: 9712, p: "+$8,401.20", sh: "1.81", dd: "-2.71%", d: "ok", st: "DONE" },
                { id: "RP-0117", s: "mean-revert-v2 · 22",   w: "2026-04-12 → 05-09", sg: 6182,  fl: 4922, p: "+$2,108.10", sh: "1.22", dd: "-1.04%", d: "ok", st: "DONE" },
                { id: "RP-0116", s: "breakout-atr-v1 · 7",   w: "2026-04-01 → 05-01", sg: 3214,  fl: 2418, p: "+$612.40",   sh: "0.94", dd: "-0.81%", d: "ok", st: "DONE" },
                { id: "RP-0115", s: "regime-flip-v0 · 3",    w: "2026-03-01 → 05-01", sg: 2841,  fl: 2104, p: "−$408.10",   sh: "−0.18", dd: "-3.42%", d: "drift", st: "FAIL" },
                { id: "RP-0114", s: "mass-momentum-v3 · 40", w: "2026-03-01 → 05-01", sg: 11420, fl: 8214, p: "+$6,118.40", sh: "1.78", dd: "-2.81%", d: "ok", st: "DONE" },
                { id: "RP-0113", s: "funding-skew-v1 · 11",  w: "2026-04-01 → 05-09", sg: 1812,  fl: 1404, p: "+$1,184.20", sh: "1.14", dd: "-1.04%", d: "ok", st: "DONE" },
                { id: "RP-0112", s: "mean-revert-v2 · 21",   w: "2026-04-12 → 05-09", sg: 6101,  fl: 4810, p: "+$1,841.10", sh: "1.18", dd: "-1.12%", d: "ok", st: "DONE" },
              ].map(r => (
                <tr key={r.id} className="row-hover">
                  <td className="mono">{r.id}</td>
                  <td className="mono">{r.s}</td>
                  <td className="mono" style={{ color: "var(--text-mid)" }}>{r.w}</td>
                  <td className="mono">{r.sg.toLocaleString()}</td>
                  <td className="mono">{r.fl.toLocaleString()}</td>
                  <td className="mono" style={{ color: r.p.startsWith("+") ? "var(--ok)" : "var(--block)" }}>{r.p}</td>
                  <td className="mono">{r.sh}</td>
                  <td className="mono" style={{ color: "var(--block)" }}>{r.dd}</td>
                  <td><Chip kind={r.d === "ok" ? "ok" : "warn"}>{r.d}</Chip></td>
                  <td><Chip kind={r.st === "DONE" ? "ok" : "block"}>{r.st}</Chip></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>
    </div>
  );
}

window.SignalsPage = SignalsPage;
window.ExecutionsPage = ExecutionsPage;
window.PositionsPage = PositionsPage;
window.SymbolsPage = SymbolsPage;
window.PaperTradingPage = PaperTradingPage;
window.ReplayPage = ReplayPage;
===== END FILE: pages-operate.jsx =====

===== FILE: pages-inspect.jsx =====
// Inspect section: Trainer Monitor, Coverage/Atlas, Script Registry, Monitor Center, Audit Ledger
const { TRAINER_PRED, AUDIT, makeSpark, makeEquityPath } = window.AIBOT;

function TrainerMonitorPage() {
  const loss = makeEquityPath(900, 160, 96);
  return (
    <div>
      <PageHeader screen="11 Trainer Monitor" sub="hybrid-v4.2 · ckpt 0291 · step 184,201 · prediction stream"
        title="TRAINER MONITOR"
        chips={<><Chip kind="ok">TRAINING · LIVE</Chip><Chip kind="warn">DRIFT · 1 SYM</Chip><Chip>loss 0.0382</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(6, minmax(0,1fr))", gap: 12, marginBottom: 16 }}>
        {[
          { l: "step",        v: "184,201",   t: "var(--text)" },
          { l: "epoch",       v: "47 / 50",   t: "var(--text)" },
          { l: "loss",        v: "0.0382",    t: "var(--ok)" },
          { l: "val loss",    v: "0.0411",    t: "var(--ok)" },
          { l: "lr",          v: "3.2e-4",    t: "var(--text)" },
          { l: "tps",         v: "12,481",    t: "var(--text)" },
        ].map(k => (
          <div key={k.l} className="panel" style={{ padding: "12px 14px" }}>
            <span className="label-mono">{k.l}</span>
            <div className="kpi-num" style={{ fontSize: 18, marginTop: 6, color: k.t }}>{k.v}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,2fr) minmax(0,1fr)", gap: 16, marginBottom: 16 }}>
        <Panel title="// training loss · val loss · 96 steps">
          <svg viewBox="0 0 900 160" width="100%" height="160" preserveAspectRatio="none">
            {[0.25, 0.5, 0.75].map(p => <line key={p} x1="0" x2="900" y1={160 * p} y2={160 * p} stroke="var(--border)" strokeDasharray="2 3" />)}
            <path d={loss.d} stroke="var(--ok)" fill="none" strokeWidth="1.4" />
            <path d={makeEquityPath(900, 160, 96).d} stroke="var(--accent)" fill="none" strokeWidth="1.2" strokeDasharray="3 4" opacity="0.7" />
          </svg>
          <div className="mono" style={{ fontSize: 10, color: "var(--text-dim)", display: "flex", gap: 18, marginTop: 4 }}>
            <span><span style={{ color: "var(--ok)" }}>━</span> train loss</span>
            <span><span style={{ color: "var(--accent)" }}>┄</span> val loss</span>
          </div>
        </Panel>
        <Panel title="// model lineage">
          {[
            ["model_id", "hybrid-v4.2"],
            ["checkpoint", "0291"],
            ["base", "hybrid-v4.1-ckpt0188"],
            ["arch", "tcn-transformer-hybrid"],
            ["params", "12.4M"],
            ["feature schema", "v18 · 184 cols"],
            ["target", "fwd-return-15m · classified"],
            ["calibration", "platt + isotonic"],
            ["last promote", "2026-05-08 14:21 UTC"],
            ["sha256", "8be1…02af"],
            ["audit-pinned", "yes"],
          ].map(r => (
            <div key={r[0]} style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", borderBottom: "1px solid var(--border)" }}>
              <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>{r[0]}</span>
              <span className="mono" style={{ fontSize: 11, color: "var(--text)" }}>{r[1]}</span>
            </div>
          ))}
        </Panel>
      </div>

      <Panel title="// prediction monitor · per-symbol" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>symbol</th><th>accuracy</th><th>mae</th><th>brier</th><th>drift (KS)</th><th>last pub</th><th>calibration</th><th>verdict</th></tr></thead>
          <tbody>
            {TRAINER_PRED.map(p => {
              const acc = p.acc;
              const drift = p.drift;
              const stale = parseFloat(p.last) > 2.5;
              return (
                <tr key={p.sym} className="row-hover">
                  <td className="mono">{p.sym}</td>
                  <td className="mono">
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <div style={{ width: 60, height: 5, background: "var(--bg)", border: "1px solid var(--border)" }}>
                        <div style={{ width: `${(acc - 0.5) * 800}%`, height: "100%", background: acc >= 0.58 ? "var(--ok)" : "var(--accent)" }} />
                      </div>
                      <span>{acc.toFixed(3)}</span>
                    </div>
                  </td>
                  <td className="mono">{p.mae.toFixed(4)}</td>
                  <td className="mono">{p.brier.toFixed(3)}</td>
                  <td className="mono" style={{ color: drift > 0.15 ? "var(--block)" : drift > 0.1 ? "var(--accent)" : "var(--ok)" }}>{drift.toFixed(2)}</td>
                  <td className="mono" style={{ color: stale ? "var(--accent)" : "var(--text-dim)" }}>{p.last}</td>
                  <td><Chip kind={acc >= 0.58 ? "ok" : "warn"}>{acc >= 0.58 ? "calibrated" : "drift"}</Chip></td>
                  <td><Chip kind={drift > 0.15 ? "block" : "ok"}>{drift > 0.15 ? "HALT" : "OK"}</Chip></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// feature importance · top-12">
          {[
            ["ret_15m_zscore", 0.94], ["orderflow_imbalance_1m", 0.87], ["funding_skew_8h", 0.74],
            ["realized_vol_1h", 0.71], ["atr_pct_4h", 0.65], ["macd_div_4h", 0.61],
            ["oi_delta_15m", 0.58], ["taker_buy_ratio_5m", 0.54], ["vwap_dev_1h", 0.49],
            ["btc_corr_1h", 0.45], ["regime_flag", 0.41], ["news_sentiment_1h", 0.28],
          ].map(([k, v]) => (
            <div key={k} style={{ display: "grid", gridTemplateColumns: "180px 1fr 40px", gap: 10, padding: "4px 0", alignItems: "center" }}>
              <span className="mono" style={{ fontSize: 11 }}>{k}</span>
              <div style={{ height: 5, background: "var(--bg)", border: "1px solid var(--border)" }}>
                <div style={{ width: `${v * 100}%`, height: "100%", background: "var(--accent)" }} />
              </div>
              <span className="mono" style={{ fontSize: 10, textAlign: "right", color: "var(--text-dim)" }}>{v.toFixed(2)}</span>
            </div>
          ))}
        </Panel>
        <Panel title="// training events">
          {[
            { t: "13:38:41", k: "checkpoint.save", d: "ckpt 0291 → store · 184,201" },
            { t: "13:22:11", k: "schema.bump",    d: "feature schema v18 (184 cols) · audit OK" },
            { t: "12:48:02", k: "drift.alert",    d: "SOL-USDT drift > 0.15 · auto-pause armed" },
            { t: "12:12:51", k: "calibration",    d: "platt+isotonic refit · brier ↓ 0.011" },
            { t: "11:48:33", k: "epoch.advance",  d: "epoch 46 → 47 · loss 0.0411 → 0.0382" },
            { t: "10:11:42", k: "data.window",    d: "rolled 14d → 30d, replay 3,212k bars" },
          ].map((e, i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "70px 130px 1fr", gap: 10, padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
              <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>{e.t}</span>
              <span className="mono" style={{ fontSize: 11, color: "var(--accent)" }}>{e.k}</span>
              <span className="mono" style={{ fontSize: 11 }}>{e.d}</span>
            </div>
          ))}
        </Panel>
      </div>
    </div>
  );
}

function CoverageAtlasPage() {
  const sections = [
    { tier: "A", group: "TRAINER", items: [
      ["data.ingestion",      "raw-reviewed", "ok"],
      ["feature.materialize", "raw-reviewed", "ok"],
      ["target.labeling",     "raw-reviewed", "ok"],
      ["model.train",         "raw-reviewed", "ok"],
      ["model.eval",          "raw-reviewed", "ok"],
      ["model.calibrate",     "raw-reviewed", "ok"],
      ["model.promote",       "raw-reviewed", "ok"],
      ["prediction.publish",  "raw-reviewed", "ok"],
    ]},
    { tier: "A", group: "ORCHESTRATOR", items: [
      ["signal.compose",      "raw-reviewed", "ok"],
      ["signal.attribution",  "raw-reviewed", "ok"],
      ["queue.bounded",       "raw-reviewed", "ok"],
      ["dedup.window",        "raw-reviewed", "ok"],
      ["lineage.chain",       "raw-reviewed", "ok"],
    ]},
    { tier: "A", group: "RISK GATEWAY", items: [
      ["gate.contract",       "raw-reviewed", "ok"],
      ["live.flag",           "raw-reviewed", "ok"],
      ["cross.margin.block",  "raw-reviewed", "ok"],
      ["leverage.cap",        "raw-reviewed", "ok"],
      ["adjust.leverage",     "evidence-pending", "warn"],
      ["kill.switch",         "raw-reviewed", "ok"],
    ]},
    { tier: "A", group: "EXECUTION", items: [
      ["paper.adapter",       "raw-reviewed", "ok"],
      ["replay.adapter",      "raw-reviewed", "ok"],
      ["fill.semantics",      "raw-reviewed", "ok"],
      ["ledger.cost-basis",   "raw-reviewed", "ok"],
      ["live.adapter",        "blocked",      "block"],
    ]},
    { tier: "B", group: "AUDIT", items: [
      ["chain.integrity",     "raw-reviewed", "ok"],
      ["hash.algo",           "raw-reviewed", "ok"],
      ["forensic.replay",     "evidence-pending", "warn"],
    ]},
    { tier: "B", group: "AI LAYER", items: [
      ["claude.admin",        "raw-reviewed", "ok"],
      ["ollama.summary",      "evidence-pending", "warn"],
      ["codex.review",        "evidence-pending", "warn"],
    ]},
  ];
  return (
    <div>
      <PageHeader screen="12 Coverage Atlas" sub="trainer.atlas · raw evidence coverage · audit-linked" title="COVERAGE / ATLAS"
        chips={<><Chip kind="ok">TIER A · 31/31</Chip><Chip kind="warn">TIER B · 5/8</Chip><Chip>OVERALL 36/39</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12, marginBottom: 16 }}>
        {[
          { l: "raw-reviewed",     v: "31", t: "var(--ok)" },
          { l: "evidence-pending", v: "3",  t: "var(--accent)" },
          { l: "blocked",          v: "1",  t: "var(--block)" },
          { l: "stub",             v: "0",  t: "var(--text)" },
        ].map(k => (
          <div key={k.l} className="panel" style={{ padding: "12px 14px" }}>
            <span className="label-mono">{k.l}</span>
            <div className="kpi-num" style={{ fontSize: 24, marginTop: 6, color: k.t }}>{k.v}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0,1fr))", gap: 16 }}>
        {sections.map(g => (
          <Panel key={g.group} title={`// ${g.group} · tier ${g.tier}`}>
            {g.items.map(([k, status, tone]) => (
              <div key={k} style={{ display: "grid", gridTemplateColumns: "1fr auto auto", gap: 10, padding: "5px 0", borderBottom: "1px solid var(--border)", alignItems: "center" }}>
                <span className="mono" style={{ fontSize: 12 }}>{k}</span>
                <span className="mono" style={{ fontSize: 10, color: tone === "ok" ? "var(--ok)" : tone === "warn" ? "var(--accent)" : "var(--block)" }}>{status}</span>
                <Chip kind={tone === "ok" ? "ok" : tone === "warn" ? "warn" : "block"}>{tone === "ok" ? "✓" : tone === "warn" ? "!" : "✗"}</Chip>
              </div>
            ))}
          </Panel>
        ))}
      </div>
    </div>
  );
}

function ScriptRegistryPage() {
  const ROWS = [
    { id: "S-0001", path: "scripts/trainer/train_loop.py",       v: "1.18.0", hash: "a019…41bc", role: "trainer",     last: "13:38:41", state: "MATCH" },
    { id: "S-0002", path: "scripts/trainer/eval_pipeline.py",   v: "1.11.2", hash: "f2c4…91ae", role: "trainer",     last: "13:33:01", state: "MATCH" },
    { id: "S-0003", path: "scripts/trainer/calibrate.py",       v: "1.04.1", hash: "b8d1…77c0", role: "trainer",     last: "12:48:11", state: "MATCH" },
    { id: "S-0004", path: "scripts/orchestrator/compose.py",    v: "2.04.0", hash: "44ee…ae21", role: "orchestrator",last: "13:42:11", state: "MATCH" },
    { id: "S-0005", path: "scripts/orchestrator/lineage.py",    v: "2.01.0", hash: "31ba…b7c4", role: "orchestrator",last: "13:41:58", state: "MATCH" },
    { id: "S-0006", path: "scripts/risk/gateway.py",            v: "3.02.1", hash: "00aa…1e7f", role: "risk",         last: "13:42:11", state: "MATCH" },
    { id: "S-0007", path: "scripts/risk/policies.yaml",         v: "0.18.0", hash: "9d72…5b8a", role: "risk-policy",  last: "13:11:01", state: "DRIFT" },
    { id: "S-0008", path: "scripts/execution/paper.py",         v: "1.07.0", hash: "5cef…83b1", role: "execution",   last: "13:42:01", state: "MATCH" },
    { id: "S-0009", path: "scripts/execution/replay.py",        v: "1.03.2", hash: "1100…aaff", role: "execution",   last: "13:34:21", state: "MATCH" },
    { id: "S-0010", path: "scripts/audit/chain.py",             v: "1.21.0", hash: "7a02…be11", role: "audit",       last: "13:42:11", state: "MATCH" },
    { id: "S-0011", path: "scripts/ai/claude_admin.py",         v: "0.08.0", hash: "1182…3322", role: "ai",          last: "13:21:41", state: "DRIFT" },
    { id: "S-0012", path: "scripts/ai/ollama_summary.py",        v: "0.04.0", hash: "5642…ee22", role: "ai",          last: "13:01:12", state: "DRIFT" },
    { id: "S-0013", path: "scripts/ai/codex_review.py",          v: "0.02.0", hash: "3334…ab19", role: "ai",          last: "12:21:31", state: "STUB"  },
    { id: "S-0014", path: "scripts/scaffold/validate.py",       v: "1.04.0", hash: "8be1…02af", role: "scaffold",    last: "13:38:41", state: "MATCH" },
    { id: "S-0015", path: "scripts/redis/migrate_namespaces.py", v: "1.02.0", hash: "abcd…1234", role: "redis",       last: "10:18:01", state: "MATCH" },
    { id: "S-0016", path: "scripts/postgres/schema.sql",        v: "0.31.0", hash: "ef21…7711", role: "postgres",    last: "10:18:01", state: "MATCH" },
  ];
  return (
    <div>
      <PageHeader screen="13 Script Registry" sub="canonical scripts · sha256-pinned · runtime hash compared" title="SCRIPT REGISTRY"
        chips={<><Chip kind="ok">13 MATCH</Chip><Chip kind="warn">3 DRIFT</Chip><Chip kind="block">0 MISSING</Chip></>} />

      <div style={{ display: "flex", gap: 10, marginBottom: 12 }}>
        <input className="input" placeholder="search path, hash, role…" style={{ width: 360 }} />
        <Chip>ROLE · all</Chip><Chip>STATE · all</Chip>
        <span style={{ flex: 1 }} />
        <button className="btn">RE-HASH</button>
        <button className="btn">EXPORT MANIFEST</button>
      </div>

      <Panel title="// canonical scripts · 16 of 247" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>id</th><th>path</th><th>role</th><th>v</th><th>sha256</th><th>last seen</th><th>state</th><th></th></tr></thead>
          <tbody>
            {ROWS.map(r => (
              <tr key={r.id} className="row-hover">
                <td className="mono">{r.id}</td>
                <td className="mono" style={{ fontSize: 11 }}>{r.path}</td>
                <td className="mono" style={{ color: "var(--text-mid)" }}>{r.role}</td>
                <td className="mono">{r.v}</td>
                <td className="mono" style={{ color: "var(--text-dim)", fontSize: 10.5 }}>{r.hash}</td>
                <td className="mono" style={{ color: "var(--text-dim)" }}>{r.last}</td>
                <td><Chip kind={r.state === "MATCH" ? "ok" : r.state === "DRIFT" ? "warn" : r.state === "STUB" ? "warn" : "block"}>{r.state}</Chip></td>
                <td><button className="btn">diff</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

function MonitorCenterPage() {
  const MONS = [
    ["redis.ns.aibotv2",      "ok",    "keys 12,481 · evicted 0",                "00:00:00.2"],
    ["redis.legacy.write",    "ok",    "0 writes detected · isolation enforced", "00:00:00.4"],
    ["postgres.lag",          "ok",    "lag 0ms · pgbouncer 12 idle",            "00:00:00.8"],
    ["audit.chain",            "ok",    "1,204,481 links · 0 breaks",             "00:00:00.6"],
    ["orchestrator.queue",    "ok",    "0 stuck · backpressure 0%",              "00:00:00.7"],
    ["trainer.heartbeat",     "ok",    "5 / 5 workers ack",                       "00:00:01.4"],
    ["risk.gate.latency",     "ok",    "p99 1.41ms · p999 2.18ms",                "00:00:00.3"],
    ["execution.replay.det",  "ok",    "byte-identical vs golden",                "00:00:00.5"],
    ["live.adapter.lock",     "block", "armed · operator approval required",      "00:00:00.3"],
    ["model.drift.ks",        "warn",  "SOL-USDT KS 0.18 > 0.15",                 "00:00:02.1"],
    ["feature.freshness",     "warn",  "11 symbols > 2.5s in last hour",          "00:00:01.0"],
    ["claude.verify.lag",     "warn",  "3 ollama packets unverified",             "00:00:11.0"],
    ["mobile.readiness.beta", "dim",   "iOS beta build · n/a yet",                "00:11:42.0"],
    ["build.scaffold.cron",   "ok",    "cron 5m · last 14:02 · PASS",             "00:01:08.0"],
  ];
  return (
    <div>
      <PageHeader screen="14 Monitor Center" sub="active monitors · alert rules · escalation" title="MONITOR CENTER"
        chips={<><Chip kind="ok">11 OK</Chip><Chip kind="warn">3 WARN</Chip><Chip kind="block">1 BLOCK</Chip></>} />

      <Panel title="// monitors · 14 active" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>monitor</th><th>state</th><th>detail</th><th>since</th><th>escalation</th><th></th></tr></thead>
          <tbody>
            {MONS.map(([name, st, det, since], i) => (
              <tr key={name} className="row-hover">
                <td className="mono">{name}</td>
                <td><Chip kind={st === "ok" ? "ok" : st === "warn" ? "warn" : st === "block" ? "block" : null}>{st.toUpperCase()}</Chip></td>
                <td className="mono" style={{ fontSize: 11.5, color: "var(--text-mid)" }}>{det}</td>
                <td className="mono" style={{ color: "var(--text-dim)" }}>{since}</td>
                <td className="mono" style={{ fontSize: 11, color: "var(--text-mid)" }}>{i % 4 === 0 ? "page operator" : i % 4 === 1 ? "slack #ai-bot-ops" : i % 4 === 2 ? "claude.admin verify" : "log only"}</td>
                <td><button className="btn">silence</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

function AuditLedgerPage() {
  const more = Array.from({ length: 14 }, (_, i) => ({
    seq: `1,204,${(465 - i).toString().padStart(3,"0")}`,
    t: `13:41:${String(45 - i).padStart(2, "0")}.${String((i*131)%999).padStart(3,"0")}`,
    actor: ["orchestrator","risk-gateway","trainer","execution","operator","audit"][i % 6],
    action: ["signal.publish","gate.allow","prediction.publish","paper.fill","gate.block","config.update","feature.refresh","ledger.lot"][i % 8],
    target: `01HW9F${(i*3).toString(36).toUpperCase().slice(0,4)}`,
    prev: `${(0x1000 + i*7).toString(16)}…${(0x8000 - i*3).toString(16)}`,
    curr: `${(0x1100 + i*11).toString(16)}…${(0x8800 - i*7).toString(16)}`,
    verdict: i === 4 || i === 9 ? "block" : "ok",
  }));
  const ALL = [...AUDIT, ...more];
  return (
    <div>
      <PageHeader screen="15 Audit Ledger" sub="append-only chain · sha256-linked · forensic-grade"
        title="AUDIT LEDGER"
        chips={<><Chip kind="ok">CHAIN OK · 0 BREAKS</Chip><Chip>1,204,481 LINKS</Chip><Chip>head a017…23dd</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12, marginBottom: 16 }}>
        {[
          { l: "links · all-time",   v: "1,204,481", t: "var(--text)" },
          { l: "links · 24h",        v: "187,402",   t: "var(--text)" },
          { l: "chain breaks",       v: "0",         t: "var(--ok)" },
          { l: "forensic replays",   v: "12 / 12",   t: "var(--ok)" },
        ].map(k => (
          <div key={k.l} className="panel" style={{ padding: "12px 14px" }}>
            <span className="label-mono">{k.l}</span>
            <div className="kpi-num" style={{ fontSize: 22, marginTop: 6, color: k.t }}>{k.v}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", gap: 10, marginBottom: 12 }}>
        <input className="input" placeholder="search target, hash, actor…" style={{ width: 360 }} />
        <Chip>ACTOR · all</Chip><Chip>ACTION · all</Chip><Chip>VERDICT · all</Chip>
        <span style={{ flex: 1 }} />
        <button className="btn">VERIFY CHAIN</button>
        <button className="btn">EXPORT NDJSON</button>
      </div>

      <Panel title="// chain · tail 22" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>seq</th><th>time</th><th>actor</th><th>action</th><th>target</th><th>prev_hash</th><th>curr_hash</th><th>verdict</th></tr></thead>
          <tbody>
            {ALL.map(r => (
              <tr key={r.seq} className="row-hover">
                <td className="mono">{r.seq}</td>
                <td className="mono" style={{ color: "var(--text-dim)" }}>{r.t}</td>
                <td className="mono" style={{ color: "var(--text-mid)" }}>{r.actor}</td>
                <td className="mono">{r.action}</td>
                <td className="mono" style={{ color: "var(--accent)" }}>{r.target}</td>
                <td className="mono" style={{ color: "var(--text-dim)", fontSize: 10.5 }}>{r.prev}</td>
                <td className="mono" style={{ color: "var(--text)", fontSize: 10.5 }}>{r.curr}</td>
                <td><Chip kind={r.verdict === "ok" ? "ok" : "block"}>{r.verdict.toUpperCase()}</Chip></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

window.TrainerMonitorPage = TrainerMonitorPage;
window.CoverageAtlasPage = CoverageAtlasPage;
window.ScriptRegistryPage = ScriptRegistryPage;
window.MonitorCenterPage = MonitorCenterPage;
window.AuditLedgerPage = AuditLedgerPage;
===== END FILE: pages-inspect.jsx =====

===== FILE: pages-admin.jsx =====
// Admin section: Live Readiness, Config/Strategy/Trainer/Orchestrator/Execution Admin
const { RISK_RULES } = window.AIBOT;

function LiveReadinessPage() {
  const ITEMS = [
    { n: 1,  k: "live.adapter.implementation",       s: "block", e: "scripts/execution/live.py is stub", who: "execution",   est: "P0" },
    { n: 2,  k: "live.adapter.contract.tests",       s: "block", e: "0/24 contract tests written",      who: "execution",   est: "P0" },
    { n: 3,  k: "exchange.connector.matrix",         s: "block", e: "binance + bybit + okx connector heartbeats", who: "execution", est: "P0" },
    { n: 4,  k: "subaccount.isolation",              s: "warn",  e: "ledger supports it, no e2e proof",  who: "execution",   est: "P1" },
    { n: 5,  k: "kill.switch.physical",              s: "warn",  e: "redis-backed, no hardware backstop", who: "risk",        est: "P1" },
    { n: 6,  k: "operator.dual-control",             s: "block", e: "2-of-3 sign-off flow not wired",    who: "risk",        est: "P0" },
    { n: 7,  k: "leverage.cap.live",                 s: "ok",    e: "policy rev 18 · 1x · pinned",       who: "risk",        est: "—"  },
    { n: 8,  k: "cross.margin.in.live",              s: "ok",    e: "ISOLATED enforced at gate",         who: "risk",        est: "—"  },
    { n: 9,  k: "feature.freshness.budget",          s: "warn",  e: "11 syms > 2.5s/h · burn rate 1.4x", who: "trainer",     est: "P1" },
    { n: 10, k: "model.drift.halt",                  s: "warn",  e: "auto-pause armed, never fired",     who: "trainer",     est: "P1" },
    { n: 11, k: "audit.chain.live.witness",          s: "warn",  e: "external witness service not wired", who: "audit",       est: "P1" },
    { n: 12, k: "ops.runbook.coverage",              s: "warn",  e: "21/27 scenarios documented",        who: "ops",         est: "P2" },
    { n: 13, k: "mobile.kill.switch.parity",         s: "ok",    e: "iOS shortcut configured · paper",   who: "ops",         est: "—"  },
    { n: 14, k: "rollback.previous.checkpoint",      s: "ok",    e: "verified · ckpt 0290 reproducible", who: "trainer",     est: "—"  },
  ];
  const ok = ITEMS.filter(x => x.s === "ok").length;
  const warn = ITEMS.filter(x => x.s === "warn").length;
  const block = ITEMS.filter(x => x.s === "block").length;
  return (
    <div>
      <PageHeader screen="16 Live Readiness" sub="14-item gate · live-trading remains blocked until all green" title="LIVE READINESS"
        chips={<><Chip kind="block">LIVE · BLOCKED</Chip><Chip kind="ok">{ok}/14 GREEN</Chip><Chip kind="warn">{warn} WARN</Chip><Chip kind="block">{block} BLOCK</Chip></>} />

      <div className="panel hatch" style={{ padding: 18, marginBottom: 16, borderLeft: "3px solid var(--block)" }}>
        <Eyebrow style={{ color: "var(--block)" }}>// readiness verdict</Eyebrow>
        <div className="cond" style={{ fontSize: 22, marginTop: 4, color: "var(--block)" }}>NOT READY · 5 of 14 items blocking</div>
        <div className="mono" style={{ fontSize: 11.5, color: "var(--text-mid)", marginTop: 6, lineHeight: 1.6 }}>
          live trading cannot be enabled. all P0 items must transition to GREEN with raw evidence pinned in audit. operator dual-control sign-off
          is required after the technical gate clears. an attempt to override this gate from automation will be rejected and audit-logged.
        </div>
      </div>

      <Panel title="// readiness checklist" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>#</th><th>item</th><th>state</th><th>evidence</th><th>owner</th><th>priority</th><th></th></tr></thead>
          <tbody>
            {ITEMS.map(it => (
              <tr key={it.n} className="row-hover">
                <td className="mono" style={{ color: "var(--text-dim)" }}>{String(it.n).padStart(2,"0")}</td>
                <td className="mono">{it.k}</td>
                <td><Chip kind={it.s === "ok" ? "ok" : it.s === "warn" ? "warn" : "block"}>{it.s.toUpperCase()}</Chip></td>
                <td className="mono" style={{ fontSize: 11, color: "var(--text-mid)" }}>{it.e}</td>
                <td className="mono" style={{ color: "var(--text-mid)" }}>{it.who}</td>
                <td className="mono" style={{ color: it.est === "P0" ? "var(--block)" : it.est === "P1" ? "var(--accent)" : "var(--text-dim)" }}>{it.est}</td>
                <td><button className="btn">open evidence</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <Panel title="// dual-control sign-off · queue" style={{ marginTop: 16 }}>
        <div className="mono" style={{ fontSize: 11.5, color: "var(--text-mid)", marginBottom: 10 }}>
          required: <strong style={{ color: "var(--text)" }}>2 of 3</strong> approvers, distinct roles, not the requester
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0,1fr))", gap: 10 }}>
          {[
            { who: "wali1984",   role: "operator",   state: "REQUESTED" },
            { who: "—",           role: "engineering",state: "PENDING" },
            { who: "—",           role: "risk",       state: "PENDING" },
          ].map(p => (
            <div key={p.role} className="panel" style={{ padding: 12, background: "var(--bg)" }}>
              <Eyebrow>{p.role}</Eyebrow>
              <div className="mono" style={{ marginTop: 4 }}>{p.who}</div>
              <Chip kind={p.state === "REQUESTED" ? "warn" : null} style={{ marginTop: 8 }}>{p.state}</Chip>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

function KVTable({ rows }) {
  return (
    <table className="data">
      <tbody>
        {rows.map(([k, v, t]) => (
          <tr key={k}>
            <td className="mono" style={{ color: "var(--text-dim)", width: "40%", fontSize: 11.5 }}>{k}</td>
            <td className="mono" style={{ color: t || "var(--text)", fontSize: 11.5 }}>{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ConfigAdminPage() {
  return (
    <div>
      <PageHeader screen="17 Config Admin" sub="layered config · policy rev 18 · audit-pinned · dual-control writes" title="CONFIG ADMIN"
        chips={<><Chip kind="ok">REV 18 · CLEAN</Chip><Chip>3 pending edits</Chip><Chip kind="warn">RBAC · admin</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16 }}>
        <Panel title="// runtime · paper">
          <KVTable rows={[
            ["mode", "paper"],
            ["live.enabled", "false", "var(--block)"],
            ["adapter", "replay-v2"],
            ["leverage.cap.paper", "3x"],
            ["leverage.cap.live", "1x", "var(--text-mid)"],
            ["margin.mode", "ISOLATED"],
            ["kill.switch", "ARMED", "var(--accent)"],
            ["hedge.enabled", "false"],
            ["dca.enabled", "false"],
            ["feature.freshness.budget.s", "2.5"],
            ["dedup.window.h", "24"],
          ]} />
        </Panel>
        <Panel title="// thresholds">
          <KVTable rows={[
            ["confidence.min", "0.60"],
            ["confidence.hot", "0.80"],
            ["atr.stop.min", "1.5x"],
            ["atr.stop.max", "3.5x"],
            ["risk.per.trade.pct", "0.50%"],
            ["max.concurrent.positions", "8"],
            ["max.gross.exposure.pct", "60%"],
            ["max.daily.loss.pct", "1.50%"],
            ["drift.ks.halt", "0.15"],
            ["latency.gate.budget.ms", "2.50"],
            ["latency.publish.budget.ms", "5.00"],
          ]} />
        </Panel>
      </div>

      <Panel title="// pending edits · awaiting dual-control" style={{ marginTop: 16 }} bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>id</th><th>key</th><th>from</th><th>to</th><th>requester</th><th>approver</th><th>state</th><th></th></tr></thead>
          <tbody>
            {[
              ["E-211", "confidence.min", "0.60", "0.62", "wali1984", "—", "PENDING"],
              ["E-210", "feature.freshness.budget.s", "2.5", "2.0", "wali1984", "—", "PENDING"],
              ["E-209", "atr.stop.min", "1.5x", "1.8x", "ops",      "wali1984", "APPROVED"],
            ].map(r => (
              <tr key={r[0]} className="row-hover">
                {r.slice(0,6).map((c,i) => <td key={i} className="mono">{c}</td>)}
                <td><Chip kind={r[6] === "APPROVED" ? "ok" : "warn"}>{r[6]}</Chip></td>
                <td><button className="btn">{r[6] === "PENDING" ? "approve" : "apply"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

function StrategyAdminPage() {
  const ROWS = [
    { id: "mass-momentum-v3", v: "rev 41", st: "ACTIVE", w: "BTC,ETH,SOL,AVAX,ARB", pnl: "+$2,118", live: "blocked" },
    { id: "mean-revert-v2",   v: "rev 22", st: "ACTIVE", w: "BNB,MATIC,DOGE", pnl: "+$612",  live: "blocked" },
    { id: "breakout-atr-v1",  v: "rev 7",  st: "ACTIVE", w: "LINK,ATOM", pnl: "+$382",  live: "blocked" },
    { id: "funding-skew-v1",  v: "rev 11", st: "ACTIVE", w: "BTC,ETH", pnl: "+$208",  live: "blocked" },
    { id: "regime-flip-v0",   v: "rev 3",  st: "PAUSED", w: "—",       pnl: "−$223",  live: "blocked" },
    { id: "spread-arb-v0",    v: "rev 1",  st: "DRAFT",  w: "—",       pnl: "—",      live: "blocked" },
  ];
  return (
    <div>
      <PageHeader screen="18 Strategy Admin" sub="strategy registry · versions · weight allocation · live disabled" title="STRATEGY ADMIN"
        chips={<><Chip kind="ok">4 ACTIVE</Chip><Chip kind="warn">1 PAUSED</Chip><Chip>1 DRAFT</Chip></>} />

      <Panel title="// strategies" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>strategy</th><th>version</th><th>state</th><th>universe</th><th>paper pnl 7d</th><th>live</th><th></th></tr></thead>
          <tbody>
            {ROWS.map(r => (
              <tr key={r.id} className="row-hover">
                <td className="mono"><strong>{r.id}</strong></td>
                <td className="mono">{r.v}</td>
                <td><Chip kind={r.st === "ACTIVE" ? "ok" : r.st === "PAUSED" ? "warn" : null}>{r.st}</Chip></td>
                <td className="mono" style={{ color: "var(--text-mid)", fontSize: 11 }}>{r.w}</td>
                <td className="mono" style={{ color: r.pnl.startsWith("+") ? "var(--ok)" : r.pnl.startsWith("−") ? "var(--block)" : "var(--text-dim)" }}>{r.pnl}</td>
                <td><Chip kind="block">{r.live}</Chip></td>
                <td><button className="btn">edit</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// weight allocation · paper">
          {[
            { k: "mass-momentum-v3", w: 50 },
            { k: "mean-revert-v2",   w: 20 },
            { k: "breakout-atr-v1",  w: 15 },
            { k: "funding-skew-v1",  w: 10 },
            { k: "regime-flip-v0",   w:  5 },
          ].map(s => (
            <div key={s.k} style={{ padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span className="mono" style={{ fontSize: 12 }}>{s.k}</span>
                <span className="mono" style={{ fontSize: 12, color: "var(--accent)" }}>{s.w}%</span>
              </div>
              <div style={{ marginTop: 5, height: 5, background: "var(--bg)", border: "1px solid var(--border)" }}>
                <div style={{ width: `${s.w}%`, height: "100%", background: "var(--accent)" }} />
              </div>
            </div>
          ))}
        </Panel>
        <Panel title="// composition rules">
          {[
            ["max strategies per signal", "1"],
            ["correlation cap (per sym)", "0.65"],
            ["overlap policy", "first-wins · attribution preserved"],
            ["promotion gate", "≥ 30d paper · sharpe ≥ 1.0 · dd ≤ 5%"],
            ["demote gate", "rolling sharpe < 0.3 · 7d window"],
            ["sandbox.draft.signals", "log-only"],
          ].map(([k, v]) => (
            <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
              <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>{k}</span>
              <span className="mono" style={{ fontSize: 11, color: "var(--text)" }}>{v}</span>
            </div>
          ))}
        </Panel>
      </div>
    </div>
  );
}

function TrainerAdminPage() {
  return (
    <div>
      <PageHeader screen="19 Trainer Admin" sub="hyperparams · scheduler · checkpoints · promote / rollback" title="TRAINER ADMIN"
        chips={<><Chip kind="ok">TRAINING · LIVE</Chip><Chip>ckpt 0291</Chip><Chip>5/5 workers</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16 }}>
        <Panel title="// hyperparameters">
          <KVTable rows={[
            ["architecture", "tcn-transformer-hybrid"],
            ["base.lr", "3.2e-4"],
            ["warmup.steps", "2,000"],
            ["scheduler", "cosine · t_max 50k"],
            ["batch.size", "256"],
            ["seq.len", "96"],
            ["dropout", "0.10"],
            ["weight.decay", "1e-5"],
            ["grad.clip", "1.00"],
            ["optimizer", "adamw"],
            ["loss", "focal · α 0.25 · γ 2"],
            ["calibration", "platt + isotonic"],
          ]} />
        </Panel>
        <Panel title="// data + features">
          <KVTable rows={[
            ["data.window.days", "30"],
            ["bar.interval", "1m"],
            ["symbols.train", "BTC,ETH,SOL,AVAX,BNB,ARB,MATIC,DOGE,LINK,ATOM"],
            ["features.schema", "v18 · 184 cols"],
            ["target", "fwd-return-15m · 5-class"],
            ["augment", "noise σ 0.01 · shuffle off"],
            ["val.split", "rolling 7d"],
            ["snapshot.cadence.steps", "1,000"],
            ["max.checkpoints.retain", "12"],
          ]} />
        </Panel>
      </div>

      <Panel title="// checkpoints" style={{ marginTop: 16 }} bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>ckpt</th><th>step</th><th>train</th><th>val</th><th>sharpe</th><th>brier</th><th>promoted</th><th>sha256</th><th></th></tr></thead>
          <tbody>
            {[
              ["0291","184,201","0.0382","0.0411","1.84","0.198","yes · ACTIVE","8be1…02af","var(--ok)"],
              ["0290","183,201","0.0388","0.0419","1.81","0.201","rollback target","f2c4…91ae",""],
              ["0289","182,201","0.0394","0.0421","1.78","0.204","no","a019…41bc",""],
              ["0288","181,201","0.0401","0.0427","1.74","0.208","no","44ee…ae21",""],
              ["0287","180,201","0.0418","0.0444","1.61","0.212","no · DRIFT","31ba…b7c4","var(--accent)"],
              ["0286","179,201","0.0431","0.0458","1.42","0.219","no · DROPPED","00aa…1e7f","var(--block)"],
            ].map(r => (
              <tr key={r[0]} className="row-hover">
                {r.slice(0,7).map((c,i) => <td key={i} className="mono" style={{ color: i === 6 ? r[8] : i === 0 ? "var(--accent)" : "var(--text)" }}>{c}</td>)}
                <td className="mono" style={{ color: "var(--text-dim)", fontSize: 11 }}>{r[7]}</td>
                <td><button className="btn">{r[6].includes("ACTIVE") ? "active" : r[6].includes("DROPPED") ? "—" : "promote"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

function OrchestratorAdminPage() {
  return (
    <div>
      <PageHeader screen="20 Orchestrator Admin" sub="signal composition · attribution · queue · lineage" title="ORCHESTRATOR ADMIN"
        chips={<><Chip kind="ok">9.4/s</Chip><Chip kind="ok">0 STUCK</Chip><Chip>queue 0</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12, marginBottom: 16 }}>
        {[
          { l: "throughput",       v: "9.4 /s",    t: "var(--ok)" },
          { l: "queue depth",       v: "0",         t: "var(--ok)" },
          { l: "stuck",            v: "0",         t: "var(--ok)" },
          { l: "publish p99",       v: "3.1 ms",   t: "var(--text)" },
        ].map(k => (
          <div key={k.l} className="panel" style={{ padding: "12px 14px" }}>
            <span className="label-mono">{k.l}</span>
            <div className="kpi-num" style={{ fontSize: 22, marginTop: 6, color: k.t }}>{k.v}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16 }}>
        <Panel title="// composition rules">
          <KVTable rows={[
            ["lineage.required", "model_id + checkpoint + features_hash + policy_rev"],
            ["attribution.required", "yes (rejects without)"],
            ["signal_id.scheme", "uuidv7"],
            ["dedup.key", "(symbol, side, model_id, bar_bucket)"],
            ["dedup.window", "24h"],
            ["bounded.queue", "10,000"],
            ["backpressure", "shed lowest-confidence first"],
            ["multi-strategy.policy", "first-wins · log losers"],
          ]} />
        </Panel>
        <Panel title="// publish topics">
          <KVTable rows={[
            ["signals.published", "→ risk-gateway"],
            ["signals.blocked",   "→ audit + monitor"],
            ["fills.confirmed",   "→ ledger + audit"],
            ["predictions.raw",   "→ feature-store snapshot"],
            ["health.heartbeat",  "→ monitor-center · 1s"],
            ["redis.namespace",   "aibotv2:*"],
            ["postgres.tables",   "signals, gates, fills, lots, audit"],
          ]} />
        </Panel>
      </div>
    </div>
  );
}

function ExecutionAdminPage() {
  return (
    <div>
      <PageHeader screen="21 Execution Admin" sub="adapters · venues · subaccounts · order routing · live disabled" title="EXECUTION ADMIN"
        chips={<><Chip kind="paper">ACTIVE · replay-v2</Chip><Chip kind="block">LIVE · BLOCKED</Chip></>} />

      <Panel title="// adapters" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>adapter</th><th>kind</th><th>state</th><th>venue</th><th>last fill</th><th>latency p99</th><th>fees</th><th></th></tr></thead>
          <tbody>
            {[
              { a: "replay-v2",       k: "paper",   s: "ACTIVE",   v: "synthetic",     lf: "13:42:01", lp: "0.81ms",  fe: "exchange-mirror", st: "ok" },
              { a: "paper-v1",        k: "paper",   s: "STANDBY",  v: "synthetic",     lf: "—",         lp: "—",       fe: "exchange-mirror", st: "" },
              { a: "binance-spot",    k: "live",    s: "BLOCKED",  v: "binance-spot",  lf: "—",         lp: "—",       fe: "tier-1",          st: "block" },
              { a: "bybit-perp",      k: "live",    s: "BLOCKED",  v: "bybit-perp",    lf: "—",         lp: "—",       fe: "vip-3",           st: "block" },
              { a: "okx-spot",        k: "live",    s: "BLOCKED",  v: "okx-spot",      lf: "—",         lp: "—",       fe: "tier-1",          st: "block" },
              { a: "ccxt-fallback",   k: "live",    s: "STUB",     v: "—",             lf: "—",         lp: "—",       fe: "—",                st: "warn" },
            ].map(r => (
              <tr key={r.a} className="row-hover">
                <td className="mono"><strong>{r.a}</strong></td>
                <td className="mono">{r.k}</td>
                <td><Chip kind={r.st === "ok" ? "ok" : r.st === "block" ? "block" : r.st === "warn" ? "warn" : null}>{r.s}</Chip></td>
                <td className="mono" style={{ color: "var(--text-mid)" }}>{r.v}</td>
                <td className="mono" style={{ color: "var(--text-dim)" }}>{r.lf}</td>
                <td className="mono">{r.lp}</td>
                <td className="mono" style={{ color: "var(--text-mid)" }}>{r.fe}</td>
                <td><button className="btn">configure</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// routing policy">
          <KVTable rows={[
            ["primary.adapter (paper)", "replay-v2"],
            ["primary.adapter (live)",  "— (blocked)"],
            ["fallback", "paper-v1"],
            ["order.type.default", "LIMIT · IOC"],
            ["slippage.cap.bps", "5.0"],
            ["partial.fill.policy", "accept · ledger lot per fill"],
            ["reject.on.exchange.error", "true"],
            ["retry.max", "0 (paper) · 0 (live · blocked)"],
          ]} />
        </Panel>
        <Panel title="// fees model">
          <KVTable rows={[
            ["paper.maker.bps", "1.0"],
            ["paper.taker.bps", "5.0"],
            ["paper.funding.included", "yes"],
            ["paper.borrow.included",  "n/a (spot)"],
            ["live.maker.bps", "— (mirror tier-1)"],
            ["live.taker.bps", "— (mirror tier-1)"],
          ]} />
        </Panel>
      </div>
    </div>
  );
}

window.LiveReadinessPage = LiveReadinessPage;
window.ConfigAdminPage = ConfigAdminPage;
window.StrategyAdminPage = StrategyAdminPage;
window.TrainerAdminPage = TrainerAdminPage;
window.OrchestratorAdminPage = OrchestratorAdminPage;
window.ExecutionAdminPage = ExecutionAdminPage;
===== END FILE: pages-admin.jsx =====

===== FILE: pages-ai.jsx =====
// AI Layer: Claude Admin, Ollama Local, Codex Review

function ClaudeAdminPage() {
  return (
    <div>
      <PageHeader screen="22 Claude Admin" sub="ai supervision · narration · verification · audit-pinned" title="CLAUDE ADMIN"
        chips={<><Chip kind="ok">CONNECTED · claude-sonnet-4.5</Chip><Chip>quota 14% / day</Chip><Chip kind="warn">3 verify pending</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12, marginBottom: 16 }}>
        {[
          { l: "calls · 24h",         v: "412",     t: "var(--text)" },
          { l: "tokens · in / out",   v: "1.4M / 218k", t: "var(--text)" },
          { l: "p99 latency",         v: "2.81s",   t: "var(--text)" },
          { l: "verification rate",   v: "98.2%",   t: "var(--ok)" },
        ].map(k => (
          <div key={k.l} className="panel" style={{ padding: "12px 14px" }}>
            <span className="label-mono">{k.l}</span>
            <div className="kpi-num" style={{ fontSize: 20, marginTop: 6, color: k.t }}>{k.v}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,2fr) minmax(0,1fr)", gap: 16 }}>
        <Panel title="// recent calls" bodyStyle={{ padding: 0 }}>
          <table className="data">
            <thead><tr><th>id</th><th>time</th><th>kind</th><th>target</th><th>tokens</th><th>verify</th><th>verdict</th></tr></thead>
            <tbody>
              {[
                ["C-04481", "13:41:11", "supervise.signal", "01HW9F2Z", "412 / 184", "auto", "ok"],
                ["C-04480", "13:38:41", "verify.ollama",    "OL-0114",  "812 / 41",  "—",    "ok"],
                ["C-04479", "13:33:11", "narrate.shift",    "shift-12", "1,021 / 311","auto", "ok"],
                ["C-04478", "13:28:01", "review.code.diff", "PR-118",   "2,418 / 612","operator","approved"],
                ["C-04477", "13:21:41", "supervise.gate",   "01HW9F2D", "318 / 92",  "auto", "block"],
                ["C-04476", "13:14:11", "verify.ollama",    "OL-0113",  "742 / 38",  "—",    "ok"],
                ["C-04475", "13:01:41", "narrate.audit",    "1,204,400","612 / 211", "auto", "ok"],
                ["C-04474", "12:48:21", "supervise.signal", "01HW9F1J", "384 / 178", "auto", "block"],
                ["C-04473", "12:42:11", "review.runbook",   "RB-021",   "1,841 / 612","operator","approved"],
                ["C-04472", "12:28:41", "verify.ollama",    "OL-0112",  "812 / 44",  "—",    "ok"],
                ["C-04471", "12:11:01", "supervise.shift",  "shift-11", "2,141 / 612","auto","ok"],
              ].map(r => (
                <tr key={r[0]} className="row-hover">
                  <td className="mono">{r[0]}</td>
                  <td className="mono" style={{ color: "var(--text-dim)" }}>{r[1]}</td>
                  <td className="mono" style={{ color: "var(--accent)" }}>{r[2]}</td>
                  <td className="mono">{r[3]}</td>
                  <td className="mono" style={{ fontSize: 11, color: "var(--text-mid)" }}>{r[4]}</td>
                  <td className="mono" style={{ color: "var(--text-mid)" }}>{r[5]}</td>
                  <td><Chip kind={r[6] === "ok" || r[6] === "approved" ? "ok" : "block"}>{r[6]}</Chip></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel title="// supervision settings">
          <KVTable rows={[
            ["model", "claude-sonnet-4.5"],
            ["fallback", "claude-haiku-4.5"],
            ["supervise.signals", "on (sample 10%)"],
            ["supervise.gates",   "on (all blocks)"],
            ["verify.ollama",     "on (all)"],
            ["narrate.shift",     "every 4h"],
            ["narrate.audit.window", "1k events"],
            ["temperature", "0.2"],
            ["max.output.tokens", "1024"],
            ["timeout.ms", "10,000"],
            ["pii.redaction", "on"],
            ["telemetry.pinned", "yes · audit"],
          ]} />
        </Panel>
      </div>

      <Panel title="// shift narration · last 4h window" style={{ marginTop: 16 }}>
        <div className="mono" style={{ fontSize: 12, color: "var(--text-mid)", lineHeight: 1.7 }}>
          <div style={{ color: "var(--text-dim)" }}># shift 13 · 10:00 → 14:00 UTC · narrated by claude-sonnet-4.5</div>
          <p style={{ margin: "10px 0" }}>
            paper session opened at $103,841; closed last bar at <span style={{ color: "var(--ok)" }}>$104,112 (+0.26%)</span> on 47 closed trades.
            primary driver: <span style={{ color: "var(--accent)" }}>mass-momentum-v3</span> on BTC + AVAX with 14 of 18 wins, mean R 0.81.
            one drift alert fired on SOL-USDT (KS 0.18 &gt; 0.15) at 12:48 — auto-pause armed but did not trip; model continues to publish with degraded confidence.
          </p>
          <p style={{ margin: "10px 0" }}>
            risk gateway blocked 4 of 27 signals in this window. blocks were textbook: 2 missing_stop_policy from regime-flip-v0 draft, 1 stale_feature (3.1s), 1 leverage_above_cap from a misconfigured paper subaccount (3.4x &gt; 3.0x).
          </p>
          <p style={{ margin: "10px 0", color: "var(--block)" }}>
            no live-trading attempts. live remains BLOCKED on 5 P0 readiness items.
          </p>
        </div>
      </Panel>
    </div>
  );
}

function OllamaPage() {
  return (
    <div>
      <PageHeader screen="23 Ollama Local" sub="local model · cheap summaries · cross-checked by claude" title="OLLAMA · LOCAL ASSISTANT"
        chips={<><Chip kind="ok">CONNECTED · llama3.1:8b-instruct-q5</Chip><Chip>local · 0 net egress</Chip><Chip kind="warn">3 unverified</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12, marginBottom: 16 }}>
        {[
          { l: "calls · 24h",         v: "1,841",   t: "var(--text)" },
          { l: "p50 / p99 latency",   v: "0.21s / 1.4s",  t: "var(--text)" },
          { l: "verify success",      v: "98.2%",   t: "var(--ok)" },
          { l: "verify pending",      v: "3",       t: "var(--accent)" },
        ].map(k => (
          <div key={k.l} className="panel" style={{ padding: "12px 14px" }}>
            <span className="label-mono">{k.l}</span>
            <div className="kpi-num" style={{ fontSize: 20, marginTop: 6, color: k.t }}>{k.v}</div>
          </div>
        ))}
      </div>

      <Panel title="// packets · summaries written by ollama, cross-checked by claude" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>id</th><th>kind</th><th>target</th><th>tokens</th><th>latency</th><th>claude verdict</th><th>state</th></tr></thead>
          <tbody>
            {[
              ["OL-0118","feature.snapshot.summary","BTC-USDT @ 13:42:11","128 / 41","0.32s","ok","verified"],
              ["OL-0117","gate.block.summary","01HW9F2D","148 / 64","0.41s","ok","verified"],
              ["OL-0116","audit.window.summary","1,204,400 → 1,204,481","1,021 / 311","0.92s","ok","verified"],
              ["OL-0115","fill.summary","EX-284100","82 / 38","0.21s","ok","verified"],
              ["OL-0114","strategy.run.summary","RP-0118","812 / 411","0.84s","drift · 1 fact","pending"],
              ["OL-0113","strategy.run.summary","RP-0117","742 / 388","0.81s","ok","verified"],
              ["OL-0112","gate.block.summary","01HW9F1J","148 / 71","0.31s","drift · 2 facts","pending"],
              ["OL-0111","feature.drift.summary","SOL-USDT","384 / 144","0.51s","drift · 1 fact","pending"],
              ["OL-0110","narration.handoff","shift-12","2,141 / 612","1.21s","ok","verified"],
              ["OL-0109","signal.context","01HW9F0V","312 / 84","0.41s","ok","verified"],
            ].map(r => (
              <tr key={r[0]} className="row-hover">
                <td className="mono">{r[0]}</td>
                <td className="mono" style={{ color: "var(--accent)" }}>{r[1]}</td>
                <td className="mono">{r[2]}</td>
                <td className="mono" style={{ fontSize: 11, color: "var(--text-mid)" }}>{r[3]}</td>
                <td className="mono">{r[4]}</td>
                <td className="mono" style={{ color: r[5].includes("drift") ? "var(--accent)" : "var(--ok)", fontSize: 11 }}>{r[5]}</td>
                <td><Chip kind={r[6] === "verified" ? "ok" : "warn"}>{r[6]}</Chip></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// model + runtime">
          <KVTable rows={[
            ["model", "llama3.1:8b-instruct-q5_K_M"],
            ["host", "localhost:11434"],
            ["context.window", "8,192"],
            ["gpu", "rtx 4090 · 24gb · 41% util"],
            ["queue", "0 (max 32)"],
            ["concurrency", "4 workers"],
            ["timeout.ms", "5,000"],
            ["egress.policy", "none · local-only enforced"],
            ["temperature", "0.1"],
            ["top.p", "0.9"],
            ["verify.policy", "claude on all summaries"],
          ]} />
        </Panel>
        <Panel title="// verification drift causes · 24h">
          {[
            { r: "fact: number mismatch (rounded)", c: 7 },
            { r: "fact: missing risk-gate verdict", c: 3 },
            { r: "fact: wrong checkpoint id",        c: 2 },
            { r: "fact: hallucinated symbol",        c: 1 },
          ].map(x => (
            <div key={x.r} style={{ display: "grid", gridTemplateColumns: "1fr 40px", gap: 10, padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
              <span className="mono" style={{ fontSize: 11.5 }}>{x.r}</span>
              <span className="mono" style={{ textAlign: "right", color: "var(--accent)" }}>{x.c}</span>
            </div>
          ))}
        </Panel>
      </div>
    </div>
  );
}

function CodexPage() {
  return (
    <div>
      <PageHeader screen="24 Codex Review" sub="code review gates · milestone reviews · diff annotation" title="CODEX REVIEW"
        chips={<><Chip kind="warn">3 OPEN</Chip><Chip>milestone C</Chip><Chip kind="ok">14 SHIPPED 7d</Chip></>} />

      <Panel title="// open reviews" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>id</th><th>title</th><th>scope</th><th>files</th><th>+ / −</th><th>findings</th><th>state</th><th></th></tr></thead>
          <tbody>
            {[
              ["CR-0118", "live.adapter.skeleton",          "execution",  "8",  "+412 / −18",  "P0: contract tests missing", "BLOCK"],
              ["CR-0117", "feature.freshness.budget.tune", "trainer",    "3",  "+44 / −12",   "P2: doc update needed",       "WARN"],
              ["CR-0116", "audit.witness.service.stub",   "audit",      "4",  "+118 / −0",  "P1: external witness not wired","WARN"],
            ].map(r => (
              <tr key={r[0]} className="row-hover">
                <td className="mono">{r[0]}</td>
                <td className="mono"><strong>{r[1]}</strong></td>
                <td className="mono" style={{ color: "var(--text-mid)" }}>{r[2]}</td>
                <td className="mono">{r[3]}</td>
                <td className="mono"><span style={{ color: "var(--ok)" }}>{r[4].split(" / ")[0]}</span> / <span style={{ color: "var(--block)" }}>{r[4].split(" / ")[1]}</span></td>
                <td className="mono" style={{ fontSize: 11, color: "var(--text-mid)" }}>{r[5]}</td>
                <td><Chip kind={r[6] === "BLOCK" ? "block" : "warn"}>{r[6]}</Chip></td>
                <td><button className="btn">open</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <Panel title="// recent ships · 7d" style={{ marginTop: 16 }} bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>id</th><th>title</th><th>scope</th><th>shipped</th><th>review</th><th>follow-up</th></tr></thead>
          <tbody>
            {[
              ["CR-0115","trainer.calibration.refit","trainer","2026-05-09 12:48","approved · 2/2","none"],
              ["CR-0114","redis.namespace.migrate","platform","2026-05-08 21:12","approved · 2/2","monitor 30d"],
              ["CR-0113","gate.contract.unify","risk","2026-05-08 14:21","approved · 2/2","none"],
              ["CR-0112","paper.adapter.fee.mirror","execution","2026-05-07 11:01","approved · 2/2","none"],
              ["CR-0111","atlas.coverage.audit","platform","2026-05-06 18:42","approved · 2/2","tier B"],
              ["CR-0110","trainer.checkpoint.retain","trainer","2026-05-05 09:41","approved · 2/2","none"],
              ["CR-0109","monitor.kill.switch.cron","ops","2026-05-04 17:01","approved · 2/2","none"],
            ].map(r => (
              <tr key={r[0]} className="row-hover">
                {r.map((c,i) => <td key={i} className="mono" style={{ color: i === 4 ? "var(--ok)" : i === 3 ? "var(--text-dim)" : i === 5 ? "var(--text-mid)" : "var(--text)" }}>{c}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// review gates">
          <KVTable rows={[
            ["min approvers · code", "2 of 3"],
            ["min approvers · risk-policy", "3 of 3"],
            ["required reviewers · risk", "risk.admin"],
            ["required reviewers · execution", "exec.lead"],
            ["block.on.contract.tests", "yes"],
            ["block.on.audit.coverage.regression", "yes"],
            ["claude.review.opt-in", "all PRs · advisory"],
            ["sla.first.touch.hours", "4"],
            ["sla.merge.business-hours", "24"],
          ]} />
        </Panel>
        <Panel title="// claude advisory · queued">
          <div className="mono" style={{ fontSize: 12, lineHeight: 1.7, color: "var(--text-mid)" }}>
            <p style={{ margin: "0 0 8px" }}><span style={{ color: "var(--accent)" }}>CR-0118</span> — the new live adapter skeleton exposes <code>place_order</code> without a precondition that asserts <code>config.live.enabled == false → reject</code>. recommend a guard at adapter entry, not only at gateway, so the lock is defence-in-depth.</p>
            <p style={{ margin: "8px 0" }}><span style={{ color: "var(--accent)" }}>CR-0117</span> — tightening freshness from 2.5s → 2.0s will likely push burn-rate above 1.5x on SOL + DOGE during US open. recommend phased: 2.3s for 7d, observe, then 2.0s.</p>
            <p style={{ margin: "8px 0 0" }}><span style={{ color: "var(--accent)" }}>CR-0116</span> — audit witness stub should produce a verifiable receipt even when disabled (no-op record), so absence of evidence remains explicit.</p>
          </div>
        </Panel>
      </div>
    </div>
  );
}

window.ClaudeAdminPage = ClaudeAdminPage;
window.OllamaPage = OllamaPage;
window.CodexPage = CodexPage;
===== END FILE: pages-ai.jsx =====

===== FILE: pages-system.jsx =====
// System: System Health, Build/Validation, Mobile Readiness

function SystemHealthPage() {
  const SVC = [
    { name: "trainer",       host: "trainer-01.lan",   v: "1.18.0", up: "11d 14h", cpu: 41, mem: 62, disk: 18, net: "1.2 MB/s", st: "ok" },
    { name: "orchestrator",  host: "orch-01.lan",      v: "2.04.0", up: "11d 14h", cpu: 18, mem: 28, disk: 4,  net: "0.8 MB/s", st: "ok" },
    { name: "risk-gateway",  host: "risk-01.lan",      v: "3.02.1", up: "11d 14h", cpu:  8, mem: 12, disk: 2,  net: "0.4 MB/s", st: "ok" },
    { name: "execution",     host: "exec-01.lan",      v: "1.07.0", up: "11d 14h", cpu: 12, mem: 18, disk: 6,  net: "0.3 MB/s", st: "ok" },
    { name: "audit",          host: "audit-01.lan",     v: "1.21.0", up: "21d 02h", cpu:  6, mem: 14, disk: 38, net: "0.1 MB/s", st: "ok" },
    { name: "redis",         host: "redis-01.lan",     v: "7.2.4",  up: "21d 02h", cpu: 11, mem: 22, disk: 12, net: "1.6 MB/s", st: "ok" },
    { name: "postgres",      host: "pg-01.lan",        v: "16.2",   up: "21d 02h", cpu:  8, mem: 41, disk: 64, net: "0.4 MB/s", st: "ok" },
    { name: "ollama",        host: "ai-gpu-01.lan",    v: "0.1.41", up: "11d 14h", cpu: 14, mem: 38, disk: 22, net: "0.1 MB/s", st: "ok" },
    { name: "monitor",       host: "mon-01.lan",       v: "0.8.2",  up: "11d 14h", cpu:  4, mem:  8, disk: 4,  net: "0.2 MB/s", st: "ok" },
  ];
  return (
    <div>
      <PageHeader screen="25 System Health" sub="services · hosts · resources · heartbeat 1s" title="SYSTEM HEALTH"
        chips={<><Chip kind="ok">9 / 9 SERVICES</Chip><Chip>uptime 11d 14h</Chip><Chip>0 incidents · 7d</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12, marginBottom: 16 }}>
        {[
          { l: "cpu (cluster avg)",   v: "13.8%", t: "var(--ok)" },
          { l: "mem (cluster avg)",   v: "27.1%", t: "var(--ok)" },
          { l: "disk (worst)",         v: "64%",   t: "var(--accent)" },
          { l: "net (cluster)",        v: "5.1 MB/s", t: "var(--text)" },
        ].map(k => (
          <div key={k.l} className="panel" style={{ padding: "12px 14px" }}>
            <span className="label-mono">{k.l}</span>
            <div className="kpi-num" style={{ fontSize: 22, marginTop: 6, color: k.t }}>{k.v}</div>
          </div>
        ))}
      </div>

      <Panel title="// services" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>service</th><th>host</th><th>v</th><th>uptime</th><th>cpu</th><th>mem</th><th>disk</th><th>net</th><th>state</th></tr></thead>
          <tbody>
            {SVC.map(s => (
              <tr key={s.name} className="row-hover">
                <td className="mono"><strong>{s.name}</strong></td>
                <td className="mono" style={{ color: "var(--text-mid)" }}>{s.host}</td>
                <td className="mono">{s.v}</td>
                <td className="mono" style={{ color: "var(--text-dim)" }}>{s.up}</td>
                {[s.cpu, s.mem, s.disk].map((p, i) => (
                  <td key={i} style={{ minWidth: 80 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <div style={{ flex: 1, height: 4, background: "var(--bg)", border: "1px solid var(--border)" }}>
                        <div style={{ width: `${p}%`, height: "100%", background: p > 70 ? "var(--block)" : p > 50 ? "var(--accent)" : "var(--ok)" }} />
                      </div>
                      <span className="mono" style={{ fontSize: 10, color: "var(--text-dim)", minWidth: 24, textAlign: "right" }}>{p}%</span>
                    </div>
                  </td>
                ))}
                <td className="mono" style={{ fontSize: 11 }}>{s.net}</td>
                <td><Chip kind="ok">{s.st.toUpperCase()}</Chip></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// recent incidents · 30d">
          {[
            ["2026-04-22 03:12", "redis · transient eviction spike", "5min", "resolved"],
            ["2026-04-18 11:48", "trainer · ckpt save slow",         "11min", "resolved"],
            ["2026-04-11 22:01", "postgres · replica lag 41ms",      "8min",  "resolved"],
          ].map((r, i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "150px 1fr 60px 80px", gap: 10, padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
              {r.map((c, j) => <span key={j} className="mono" style={{ fontSize: 11, color: j === 0 ? "var(--text-dim)" : j === 3 ? "var(--ok)" : "var(--text)" }}>{c}</span>)}
            </div>
          ))}
        </Panel>
        <Panel title="// dependencies · external">
          {[
            ["binance-spot · market data", "ok", "ws 14ms"],
            ["bybit · market data",         "ok", "ws 18ms"],
            ["okx · market data",           "ok", "ws 21ms"],
            ["claude · api",                "ok", "rest p99 2.8s"],
            ["coingecko · ref data",        "ok", "rest 412ms"],
            ["binance · live trading",      "blocked", "policy"],
          ].map((r, i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 80px 80px", gap: 10, padding: "5px 0", borderBottom: "1px solid var(--border)", alignItems: "center" }}>
              <span className="mono" style={{ fontSize: 11.5 }}>{r[0]}</span>
              <Chip kind={r[1] === "ok" ? "ok" : "block"}>{r[1].toUpperCase()}</Chip>
              <span className="mono" style={{ fontSize: 10, color: "var(--text-dim)", textAlign: "right" }}>{r[2]}</span>
            </div>
          ))}
        </Panel>
      </div>
    </div>
  );
}

function BuildValidationPage() {
  const { BUILD } = window.AIBOT;
  return (
    <div>
      <PageHeader screen="26 Build Validation" sub="scaffold validation · milestone reviews · evidence chain" title="BUILD / VALIDATION"
        chips={<><Chip kind="ok">5 PASS</Chip><Chip kind="warn">3 WARN</Chip><Chip>milestone C</Chip></>} />

      <div className="panel hatch" style={{ padding: 16, marginBottom: 16, borderLeft: "3px solid var(--accent)" }}>
        <Eyebrow style={{ color: "var(--accent)" }}>// roadmap · priority order</Eyebrow>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 14, marginTop: 12 }}>
          {[
            { p: "P0", n: "1", k: "live adapter implementation",     w: "execution",  s: "in-progress" },
            { p: "P0", n: "2", k: "contract tests for live adapter", w: "execution",  s: "planned" },
            { p: "P0", n: "3", k: "operator dual-control sign-off",  w: "risk + ops", s: "planned" },
            { p: "P1", n: "4", k: "exchange connector matrix",       w: "execution",  s: "stub" },
            { p: "P1", n: "5", k: "feature freshness < 2s",          w: "trainer",    s: "in-progress" },
            { p: "P1", n: "6", k: "audit witness external service",  w: "audit",      s: "stub" },
            { p: "P2", n: "7", k: "ops runbook to 100%",             w: "ops",        s: "in-progress" },
            { p: "P2", n: "8", k: "mobile parity for kill switch",    w: "ops",        s: "in-progress" },
          ].map(it => (
            <div key={it.n} className="panel" style={{ padding: 12, background: "var(--bg)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <Chip kind={it.p === "P0" ? "block" : it.p === "P1" ? "warn" : null}>{it.p}</Chip>
                <span className="mono" style={{ fontSize: 10, color: "var(--text-dim)" }}>#{it.n}</span>
              </div>
              <div className="cond" style={{ fontSize: 14, marginTop: 8 }}>{it.k}</div>
              <div className="mono" style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 4 }}>{it.w}</div>
              <Chip style={{ marginTop: 8 }} kind={it.s === "in-progress" ? "warn" : null}>{it.s}</Chip>
            </div>
          ))}
        </div>
      </div>

      <Panel title="// validation gates · last cron 14:02" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>id</th><th>gate</th><th>state</th><th>detail</th><th>evidence</th></tr></thead>
          <tbody>
            {BUILD.map(b => (
              <tr key={b.id} className="row-hover">
                <td className="mono">{b.id}</td>
                <td className="mono">{b.label}</td>
                <td><Chip kind={b.status === "PASS" ? "ok" : b.status === "WARN" ? "warn" : "block"}>{b.status}</Chip></td>
                <td className="mono" style={{ fontSize: 11.5, color: "var(--text-mid)" }}>{b.detail}</td>
                <td><button className="btn">open</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// milestone history">
          {[
            ["M-A · scaffold + atlas",         "2026-04-12", "passed"],
            ["M-B · trainer + orchestrator",    "2026-04-22", "passed"],
            ["M-C · risk + paper + audit",      "2026-05-09", "in-review"],
            ["M-D · live adapter + readiness",  "—",          "planned"],
            ["M-E · live trading enabled",     "—",          "planned"],
          ].map((r, i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 100px 100px", gap: 10, padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
              <span className="mono" style={{ fontSize: 12 }}>{r[0]}</span>
              <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>{r[1]}</span>
              <Chip kind={r[2] === "passed" ? "ok" : r[2] === "in-review" ? "warn" : null}>{r[2]}</Chip>
            </div>
          ))}
        </Panel>
        <Panel title="// cron schedule">
          <KVTable rows={[
            ["scaffold.validate", "*/5min"],
            ["redis.namespace.audit", "*/15min"],
            ["audit.chain.verify", "*/1h"],
            ["atlas.coverage.recompute", "*/1h"],
            ["readiness.checklist.refresh", "*/15min"],
            ["claude.shift.narrate", "*/4h"],
            ["codex.queue.scan", "*/10min"],
          ]} />
        </Panel>
      </div>
    </div>
  );
}

function MobileReadinessPage() {
  return (
    <div>
      <PageHeader screen="27 Mobile Readiness" sub="iOS companion · operator surface · paper parity" title="MOBILE / IPHONE READINESS"
        chips={<><Chip kind="warn">BETA</Chip><Chip kind="paper">PAPER · KILL SWITCH OK</Chip><Chip>build 0.4.1-rc2</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "320px minmax(0,1fr)", gap: 16, alignItems: "start" }}>
        <div style={{ background: "var(--bg)", padding: 18, border: "1px solid var(--border)", borderRadius: 36, position: "relative" }}>
          <div style={{ width: 110, height: 18, background: "var(--surface-3)", borderRadius: 10, margin: "0 auto 12px" }} />
          <div style={{ background: "var(--surface)", border: "1px solid var(--border)", padding: "14px 12px", borderRadius: 24 }}>
            <div className="mono" style={{ fontSize: 9, color: "var(--text-dim)" }}>14:02 UTC · op wali1984</div>
            <div className="cond" style={{ fontSize: 17, marginTop: 6 }}>AI BOT · CONTROL</div>
            <div className="hr" style={{ margin: "10px 0" }} />
            <Chip kind="block" style={{ width: "100%", textAlign: "center", padding: "8px 0" }}>LIVE · BLOCKED</Chip>
            <Chip kind="paper" style={{ width: "100%", textAlign: "center", padding: "8px 0", marginTop: 6 }}>PAPER · ACTIVE</Chip>
            <div className="hr" style={{ margin: "10px 0" }} />
            {[
              ["equity", "$104,112"],
              ["upnl", "+$15.22"],
              ["open pos", "6"],
              ["throughput", "9.4 /s"],
              ["gate latency", "0.84ms"],
            ].map(r => (
              <div key={r[0]} style={{ display: "flex", justifyContent: "space-between", padding: "4px 0" }}>
                <span className="mono" style={{ fontSize: 10.5, color: "var(--text-dim)" }}>{r[0]}</span>
                <span className="mono" style={{ fontSize: 11, color: "var(--text)" }}>{r[1]}</span>
              </div>
            ))}
            <div className="hr" style={{ margin: "10px 0" }} />
            <button className="btn danger" style={{ width: "100%", padding: "10px 0" }}>KILL SWITCH</button>
            <div className="mono" style={{ fontSize: 9, color: "var(--text-dim)", textAlign: "center", marginTop: 6 }}>requires biometric + pin</div>
          </div>
        </div>

        <div style={{ display: "grid", gap: 16 }}>
          <Panel title="// parity · mobile vs desktop">
            <table className="data">
              <thead><tr><th>feature</th><th>desktop</th><th>mobile</th><th>parity</th></tr></thead>
              <tbody>
                {[
                  ["read · mission control",          "yes", "yes", "ok"],
                  ["read · signals + executions",     "yes", "yes (read)", "ok"],
                  ["read · positions",                 "yes", "yes (read)", "ok"],
                  ["control · kill switch",            "yes", "yes (biometric)", "ok"],
                  ["control · pause strategy",         "yes", "yes (biometric)", "ok"],
                  ["control · close position",         "yes", "no (deferred · paper-only ok)", "warn"],
                  ["control · enable live",            "no",  "no", "ok"],
                  ["control · config writes",          "yes (dual)", "no", "warn"],
                  ["narration · shift summary",        "yes", "yes", "ok"],
                  ["push · gate.block · drift.alert",  "—",   "yes", "ok"],
                  ["offline mode",                    "n/a", "read-cache 5m", "—"],
                ].map((r, i) => (
                  <tr key={i} className="row-hover">
                    <td className="mono">{r[0]}</td>
                    <td className="mono" style={{ color: "var(--text-mid)" }}>{r[1]}</td>
                    <td className="mono" style={{ color: "var(--text-mid)" }}>{r[2]}</td>
                    <td><Chip kind={r[3] === "ok" ? "ok" : r[3] === "warn" ? "warn" : null}>{r[3]}</Chip></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <Panel title="// build">
              <KVTable rows={[
                ["platform", "iOS 17+ · iPhone 13 and up"],
                ["distribution", "TestFlight · internal"],
                ["build", "0.4.1-rc2"],
                ["binary size", "11.4 MB"],
                ["cold start p99", "0.81s"],
                ["push provider", "apns2 · sandbox"],
                ["biometric", "FaceID / TouchID"],
                ["secrets storage", "keychain · access-after-first-unlock"],
                ["network egress", "vpn-only · internal mesh"],
              ]} />
            </Panel>
            <Panel title="// gate · before live">
              {[
                ["dangerous controls behind biometric+pin", "ok"],
                ["session lock @ 5min idle",                "ok"],
                ["jailbreak detection",                     "ok"],
                ["pin retry lockout",                       "ok"],
                ["push delivery e2e proof",                 "warn"],
                ["offline kill-switch fallback",            "warn"],
                ["legal · disclaimers + audit log access",  "warn"],
              ].map((r, i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: "1px solid var(--border)", alignItems: "center" }}>
                  <span className="mono" style={{ fontSize: 11.5 }}>{r[0]}</span>
                  <Chip kind={r[1] === "ok" ? "ok" : "warn"}>{r[1].toUpperCase()}</Chip>
                </div>
              ))}
            </Panel>
          </div>
        </div>
      </div>
    </div>
  );
}

window.SystemHealthPage = SystemHealthPage;
window.BuildValidationPage = BuildValidationPage;
window.MobileReadinessPage = MobileReadinessPage;
===== END FILE: pages-system.jsx =====

===== FILE: module-placeholder.jsx =====
// Module placeholder — shown for nav items we haven't fully designed yet.

function ModulePlaceholder({ id, label }) {
  return (
    <div data-screen-label={`${id}`}>
      <div className="panel bracketed hatch" style={{ padding: "22px 24px", marginBottom: 16 }}>
        <span className="br-bl" /><span className="br-br" />
        <Eyebrow>// module · placeholder · not yet wired</Eyebrow>
        <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginTop: 8 }}>
          <h1 className="cond" style={{ fontSize: 30 }}>{label.toUpperCase()}</h1>
          <Chip>module · {id}</Chip>
        </div>
        <div className="mono" style={{ marginTop: 10, fontSize: 12, color: "var(--text-dim)" }}>
          This screen is part of the V2 page inventory — Mission Control, Signal Explainability, and Risk Control are the three fully-designed surfaces in this mockup.
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 16 }}>
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="panel" style={{ minHeight: 160, padding: 0, position: "relative", overflow: "hidden" }}>
            <div className="panel-head">
              <span className="panel-title">// slot · {String(i + 1).padStart(2, "0")}</span>
              <span className="label-mono" style={{ color: "var(--text-faint)" }}>placeholder</span>
            </div>
            <div className="hatch" style={{ height: 124, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>
                {label} · panel {i + 1}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

window.ModulePlaceholder = ModulePlaceholder;
===== END FILE: module-placeholder.jsx =====

===== FILE: tweaks-panel.jsx =====

// tweaks-panel.jsx
// Reusable Tweaks shell + form-control helpers.
//
// Owns the host protocol (listens for __activate_edit_mode / __deactivate_edit_mode,
// posts __edit_mode_available / __edit_mode_set_keys / __edit_mode_dismissed) so
// individual prototypes don't re-roll it. Ships a consistent set of controls so you
// don't hand-draw <input type="range">, segmented radios, steppers, etc.
//
// Usage (in an HTML file that loads React + Babel):
//
//   const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
//     "primaryColor": "#D97757",
//     "palette": ["#D97757", "#29261b", "#f6f4ef"],
//     "fontSize": 16,
//     "density": "regular",
//     "dark": false
//   }/*EDITMODE-END*/;
//
//   function App() {
//     const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
//     return (
//       <div style={{ fontSize: t.fontSize, color: t.primaryColor }}>
//         Hello
//         <TweaksPanel>
//           <TweakSection label="Typography" />
//           <TweakSlider label="Font size" value={t.fontSize} min={10} max={32} unit="px"
//                        onChange={(v) => setTweak('fontSize', v)} />
//           <TweakRadio  label="Density" value={t.density}
//                        options={['compact', 'regular', 'comfy']}
//                        onChange={(v) => setTweak('density', v)} />
//           <TweakSection label="Theme" />
//           <TweakColor  label="Primary" value={t.primaryColor}
//                        options={['#D97757', '#2A6FDB', '#1F8A5B', '#7A5AE0']}
//                        onChange={(v) => setTweak('primaryColor', v)} />
//           <TweakColor  label="Palette" value={t.palette}
//                        options={[['#D97757', '#29261b', '#f6f4ef'],
//                                  ['#475569', '#0f172a', '#f1f5f9']]}
//                        onChange={(v) => setTweak('palette', v)} />
//           <TweakToggle label="Dark mode" value={t.dark}
//                        onChange={(v) => setTweak('dark', v)} />
//         </TweaksPanel>
//       </div>
//     );
//   }
//
// ─────────────────────────────────────────────────────────────────────────────

const __TWEAKS_STYLE = `
  .twk-panel{position:fixed;right:16px;bottom:16px;z-index:2147483646;width:280px;
    max-height:calc(100vh - 32px);display:flex;flex-direction:column;
    transform:scale(var(--dc-inv-zoom,1));transform-origin:bottom right;
    background:rgba(250,249,247,.78);color:#29261b;
    -webkit-backdrop-filter:blur(24px) saturate(160%);backdrop-filter:blur(24px) saturate(160%);
    border:.5px solid rgba(255,255,255,.6);border-radius:14px;
    box-shadow:0 1px 0 rgba(255,255,255,.5) inset,0 12px 40px rgba(0,0,0,.18);
    font:11.5px/1.4 ui-sans-serif,system-ui,-apple-system,sans-serif;overflow:hidden}
  .twk-hd{display:flex;align-items:center;justify-content:space-between;
    padding:10px 8px 10px 14px;cursor:move;user-select:none}
  .twk-hd b{font-size:12px;font-weight:600;letter-spacing:.01em}
  .twk-x{appearance:none;border:0;background:transparent;color:rgba(41,38,27,.55);
    width:22px;height:22px;border-radius:6px;cursor:default;font-size:13px;line-height:1}
  .twk-x:hover{background:rgba(0,0,0,.06);color:#29261b}
  .twk-body{padding:2px 14px 14px;display:flex;flex-direction:column;gap:10px;
    overflow-y:auto;overflow-x:hidden;min-height:0;
    scrollbar-width:thin;scrollbar-color:rgba(0,0,0,.15) transparent}
  .twk-body::-webkit-scrollbar{width:8px}
  .twk-body::-webkit-scrollbar-track{background:transparent;margin:2px}
  .twk-body::-webkit-scrollbar-thumb{background:rgba(0,0,0,.15);border-radius:4px;
    border:2px solid transparent;background-clip:content-box}
  .twk-body::-webkit-scrollbar-thumb:hover{background:rgba(0,0,0,.25);
    border:2px solid transparent;background-clip:content-box}
  .twk-row{display:flex;flex-direction:column;gap:5px}
  .twk-row-h{flex-direction:row;align-items:center;justify-content:space-between;gap:10px}
  .twk-lbl{display:flex;justify-content:space-between;align-items:baseline;
    color:rgba(41,38,27,.72)}
  .twk-lbl>span:first-child{font-weight:500}
  .twk-val{color:rgba(41,38,27,.5);font-variant-numeric:tabular-nums}

  .twk-sect{font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
    color:rgba(41,38,27,.45);padding:10px 0 0}
  .twk-sect:first-child{padding-top:0}

  .twk-field{appearance:none;width:100%;height:26px;padding:0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;
    background:rgba(255,255,255,.6);color:inherit;font:inherit;outline:none}
  .twk-field:focus{border-color:rgba(0,0,0,.25);background:rgba(255,255,255,.85)}
  select.twk-field{padding-right:22px;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path fill='rgba(0,0,0,.5)' d='M0 0h10L5 6z'/></svg>");
    background-repeat:no-repeat;background-position:right 8px center}

  .twk-slider{appearance:none;-webkit-appearance:none;width:100%;height:4px;margin:6px 0;
    border-radius:999px;background:rgba(0,0,0,.12);outline:none}
  .twk-slider::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;
    width:14px;height:14px;border-radius:50%;background:#fff;
    border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}
  .twk-slider::-moz-range-thumb{width:14px;height:14px;border-radius:50%;
    background:#fff;border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}

  .twk-seg{position:relative;display:flex;padding:2px;border-radius:8px;
    background:rgba(0,0,0,.06);user-select:none}
  .twk-seg-thumb{position:absolute;top:2px;bottom:2px;border-radius:6px;
    background:rgba(255,255,255,.9);box-shadow:0 1px 2px rgba(0,0,0,.12);
    transition:left .15s cubic-bezier(.3,.7,.4,1),width .15s}
  .twk-seg.dragging .twk-seg-thumb{transition:none}
  .twk-seg button{appearance:none;position:relative;z-index:1;flex:1;border:0;
    background:transparent;color:inherit;font:inherit;font-weight:500;min-height:22px;
    border-radius:6px;cursor:default;padding:4px 6px;line-height:1.2;
    overflow-wrap:anywhere}

  .twk-toggle{position:relative;width:32px;height:18px;border:0;border-radius:999px;
    background:rgba(0,0,0,.15);transition:background .15s;cursor:default;padding:0}
  .twk-toggle[data-on="1"]{background:#34c759}
  .twk-toggle i{position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;
    background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.25);transition:transform .15s}
  .twk-toggle[data-on="1"] i{transform:translateX(14px)}

  .twk-num{display:flex;align-items:center;height:26px;padding:0 0 0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;background:rgba(255,255,255,.6)}
  .twk-num-lbl{font-weight:500;color:rgba(41,38,27,.6);cursor:ew-resize;
    user-select:none;padding-right:8px}
  .twk-num input{flex:1;min-width:0;height:100%;border:0;background:transparent;
    font:inherit;font-variant-numeric:tabular-nums;text-align:right;padding:0 8px 0 0;
    outline:none;color:inherit;-moz-appearance:textfield}
  .twk-num input::-webkit-inner-spin-button,.twk-num input::-webkit-outer-spin-button{
    -webkit-appearance:none;margin:0}
  .twk-num-unit{padding-right:8px;color:rgba(41,38,27,.45)}

  .twk-btn{appearance:none;height:26px;padding:0 12px;border:0;border-radius:7px;
    background:rgba(0,0,0,.78);color:#fff;font:inherit;font-weight:500;cursor:default}
  .twk-btn:hover{background:rgba(0,0,0,.88)}
  .twk-btn.secondary{background:rgba(0,0,0,.06);color:inherit}
  .twk-btn.secondary:hover{background:rgba(0,0,0,.1)}

  .twk-swatch{appearance:none;-webkit-appearance:none;width:56px;height:22px;
    border:.5px solid rgba(0,0,0,.1);border-radius:6px;padding:0;cursor:default;
    background:transparent;flex-shrink:0}
  .twk-swatch::-webkit-color-swatch-wrapper{padding:0}
  .twk-swatch::-webkit-color-swatch{border:0;border-radius:5.5px}
  .twk-swatch::-moz-color-swatch{border:0;border-radius:5.5px}

  .twk-chips{display:flex;gap:6px}
  .twk-chip{position:relative;appearance:none;flex:1;min-width:0;height:46px;
    padding:0;border:0;border-radius:6px;overflow:hidden;cursor:default;
    box-shadow:0 0 0 .5px rgba(0,0,0,.12),0 1px 2px rgba(0,0,0,.06);
    transition:transform .12s cubic-bezier(.3,.7,.4,1),box-shadow .12s}
  .twk-chip:hover{transform:translateY(-1px);
    box-shadow:0 0 0 .5px rgba(0,0,0,.18),0 4px 10px rgba(0,0,0,.12)}
  .twk-chip[data-on="1"]{box-shadow:0 0 0 1.5px rgba(0,0,0,.85),
    0 2px 6px rgba(0,0,0,.15)}
  .twk-chip>span{position:absolute;top:0;bottom:0;right:0;width:34%;
    display:flex;flex-direction:column;box-shadow:-1px 0 0 rgba(0,0,0,.1)}
  .twk-chip>span>i{flex:1;box-shadow:0 -1px 0 rgba(0,0,0,.1)}
  .twk-chip>span>i:first-child{box-shadow:none}
  .twk-chip svg{position:absolute;top:6px;left:6px;width:13px;height:13px;
    filter:drop-shadow(0 1px 1px rgba(0,0,0,.3))}
`;

// ── useTweaks ───────────────────────────────────────────────────────────────
// Single source of truth for tweak values. setTweak persists via the host
// (__edit_mode_set_keys → host rewrites the EDITMODE block on disk).
function useTweaks(defaults) {
  const [values, setValues] = React.useState(defaults);
  // Accepts either setTweak('key', value) or setTweak({ key: value, ... }) so a
  // useState-style call doesn't write a "[object Object]" key into the persisted
  // JSON block.
  const setTweak = React.useCallback((keyOrEdits, val) => {
    const edits = typeof keyOrEdits === 'object' && keyOrEdits !== null
      ? keyOrEdits : { [keyOrEdits]: val };
    setValues((prev) => ({ ...prev, ...edits }));
    window.parent.postMessage({ type: '__edit_mode_set_keys', edits }, '*');
    // Same-window signal so in-page listeners (deck-stage rail thumbnails)
    // can react — the parent message only reaches the host, not peers.
    window.dispatchEvent(new CustomEvent('tweakchange', { detail: edits }));
  }, []);
  return [values, setTweak];
}

// ── TweaksPanel ─────────────────────────────────────────────────────────────
// Floating shell. Registers the protocol listener BEFORE announcing
// availability — if the announce ran first, the host's activate could land
// before our handler exists and the toolbar toggle would silently no-op.
// The close button posts __edit_mode_dismissed so the host's toolbar toggle
// flips off in lockstep; the host echoes __deactivate_edit_mode back which
// is what actually hides the panel.
function TweaksPanel({ title = 'Tweaks', noDeckControls = false, children }) {
  const [open, setOpen] = React.useState(false);
  const dragRef = React.useRef(null);
  // Auto-inject a rail toggle when a <deck-stage> is on the page. The
  // toggle drives the deck's per-viewer _railVisible via window message;
  // state is mirrored from the same localStorage key the deck reads so
  // the control reflects reality across reloads. The mechanism is the
  // message — authors who want custom placement can post it directly
  // and pass noDeckControls to suppress this one.
  const hasDeckStage = React.useMemo(
    () => typeof document !== 'undefined' && !!document.querySelector('deck-stage'),
    [],
  );
  // Hide the toggle until the host has actually enabled the rail (the
  // __omelette_rail_enabled window message, posted only when the
  // omelette_deck_rail_enabled flag is on for this user). The initial read
  // covers TweaksPanel mounting after the message already arrived; the
  // listener covers the common case of mounting first.
  const [railEnabled, setRailEnabled] = React.useState(
    () => hasDeckStage && !!document.querySelector('deck-stage')?._railEnabled,
  );
  React.useEffect(() => {
    if (!hasDeckStage || railEnabled) return undefined;
    const onMsg = (e) => {
      if (e.data && e.data.type === '__omelette_rail_enabled') setRailEnabled(true);
    };
    window.addEventListener('message', onMsg);
    return () => window.removeEventListener('message', onMsg);
  }, [hasDeckStage, railEnabled]);
  const [railVisible, setRailVisible] = React.useState(() => {
    try { return localStorage.getItem('deck-stage.railVisible') !== '0'; } catch (e) { return true; }
  });
  const toggleRail = (on) => {
    setRailVisible(on);
    window.postMessage({ type: '__deck_rail_visible', on }, '*');
  };
  const offsetRef = React.useRef({ x: 16, y: 16 });
  const PAD = 16;

  const clampToViewport = React.useCallback(() => {
    const panel = dragRef.current;
    if (!panel) return;
    const w = panel.offsetWidth, h = panel.offsetHeight;
    const maxRight = Math.max(PAD, window.innerWidth - w - PAD);
    const maxBottom = Math.max(PAD, window.innerHeight - h - PAD);
    offsetRef.current = {
      x: Math.min(maxRight, Math.max(PAD, offsetRef.current.x)),
      y: Math.min(maxBottom, Math.max(PAD, offsetRef.current.y)),
    };
    panel.style.right = offsetRef.current.x + 'px';
    panel.style.bottom = offsetRef.current.y + 'px';
  }, []);

  React.useEffect(() => {
    if (!open) return;
    clampToViewport();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', clampToViewport);
      return () => window.removeEventListener('resize', clampToViewport);
    }
    const ro = new ResizeObserver(clampToViewport);
    ro.observe(document.documentElement);
    return () => ro.disconnect();
  }, [open, clampToViewport]);

  React.useEffect(() => {
    const onMsg = (e) => {
      const t = e?.data?.type;
      if (t === '__activate_edit_mode') setOpen(true);
      else if (t === '__deactivate_edit_mode') setOpen(false);
    };
    window.addEventListener('message', onMsg);
    window.parent.postMessage({ type: '__edit_mode_available' }, '*');
    return () => window.removeEventListener('message', onMsg);
  }, []);

  const dismiss = () => {
    setOpen(false);
    window.parent.postMessage({ type: '__edit_mode_dismissed' }, '*');
  };

  const onDragStart = (e) => {
    const panel = dragRef.current;
    if (!panel) return;
    const r = panel.getBoundingClientRect();
    const sx = e.clientX, sy = e.clientY;
    const startRight = window.innerWidth - r.right;
    const startBottom = window.innerHeight - r.bottom;
    const move = (ev) => {
      offsetRef.current = {
        x: startRight - (ev.clientX - sx),
        y: startBottom - (ev.clientY - sy),
      };
      clampToViewport();
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };

  if (!open) return null;
  return (
    <>
      <style>{__TWEAKS_STYLE}</style>
      <div ref={dragRef} className="twk-panel" data-noncommentable=""
           style={{ right: offsetRef.current.x, bottom: offsetRef.current.y }}>
        <div className="twk-hd" onMouseDown={onDragStart}>
          <b>{title}</b>
          <button className="twk-x" aria-label="Close tweaks"
                  onMouseDown={(e) => e.stopPropagation()}
                  onClick={dismiss}>✕</button>
        </div>
        <div className="twk-body">
          {children}
          {hasDeckStage && railEnabled && !noDeckControls && (
            <TweakSection label="Deck">
              <TweakToggle label="Thumbnail rail" value={railVisible} onChange={toggleRail} />
            </TweakSection>
          )}
        </div>
      </div>
    </>
  );
}

// ── Layout helpers ──────────────────────────────────────────────────────────

function TweakSection({ label, children }) {
  return (
    <>
      <div className="twk-sect">{label}</div>
      {children}
    </>
  );
}

function TweakRow({ label, value, children, inline = false }) {
  return (
    <div className={inline ? 'twk-row twk-row-h' : 'twk-row'}>
      <div className="twk-lbl">
        <span>{label}</span>
        {value != null && <span className="twk-val">{value}</span>}
      </div>
      {children}
    </div>
  );
}

// ── Controls ────────────────────────────────────────────────────────────────

function TweakSlider({ label, value, min = 0, max = 100, step = 1, unit = '', onChange }) {
  return (
    <TweakRow label={label} value={`${value}${unit}`}>
      <input type="range" className="twk-slider" min={min} max={max} step={step}
             value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </TweakRow>
  );
}

function TweakToggle({ label, value, onChange }) {
  return (
    <div className="twk-row twk-row-h">
      <div className="twk-lbl"><span>{label}</span></div>
      <button type="button" className="twk-toggle" data-on={value ? '1' : '0'}
              role="switch" aria-checked={!!value}
              onClick={() => onChange(!value)}><i /></button>
    </div>
  );
}

function TweakRadio({ label, value, options, onChange }) {
  const trackRef = React.useRef(null);
  const [dragging, setDragging] = React.useState(false);
  // The active value is read by pointer-move handlers attached for the lifetime
  // of a drag — ref it so a stale closure doesn't fire onChange for every move.
  const valueRef = React.useRef(value);
  valueRef.current = value;

  // Segments wrap mid-word once per-segment width runs out. The track is
  // ~248px (280 panel − 28 body pad − 4 seg pad), each button loses 12px
  // to its own padding, and 11.5px system-ui averages ~6.3px/char — so 2
  // options fit ~16 chars each, 3 fit ~10. Past that (or >3 options), fall
  // back to a dropdown rather than wrap.
  const labelLen = (o) => String(typeof o === 'object' ? o.label : o).length;
  const maxLen = options.reduce((m, o) => Math.max(m, labelLen(o)), 0);
  const fitsAsSegments = maxLen <= ({ 2: 16, 3: 10 }[options.length] ?? 0);
  if (!fitsAsSegments) {
    // <select> emits strings — map back to the original option value so the
    // fallback stays type-preserving (numbers, booleans) like the segment path.
    const resolve = (s) => {
      const m = options.find((o) => String(typeof o === 'object' ? o.value : o) === s);
      return m === undefined ? s : typeof m === 'object' ? m.value : m;
    };
    return <TweakSelect label={label} value={value} options={options}
                        onChange={(s) => onChange(resolve(s))} />;
  }
  const opts = options.map((o) => (typeof o === 'object' ? o : { value: o, label: o }));
  const idx = Math.max(0, opts.findIndex((o) => o.value === value));
  const n = opts.length;

  const segAt = (clientX) => {
    const r = trackRef.current.getBoundingClientRect();
    const inner = r.width - 4;
    const i = Math.floor(((clientX - r.left - 2) / inner) * n);
    return opts[Math.max(0, Math.min(n - 1, i))].value;
  };

  const onPointerDown = (e) => {
    setDragging(true);
    const v0 = segAt(e.clientX);
    if (v0 !== valueRef.current) onChange(v0);
    const move = (ev) => {
      if (!trackRef.current) return;
      const v = segAt(ev.clientX);
      if (v !== valueRef.current) onChange(v);
    };
    const up = () => {
      setDragging(false);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  return (
    <TweakRow label={label}>
      <div ref={trackRef} role="radiogroup" onPointerDown={onPointerDown}
           className={dragging ? 'twk-seg dragging' : 'twk-seg'}>
        <div className="twk-seg-thumb"
             style={{ left: `calc(2px + ${idx} * (100% - 4px) / ${n})`,
                      width: `calc((100% - 4px) / ${n})` }} />
        {opts.map((o) => (
          <button key={o.value} type="button" role="radio" aria-checked={o.value === value}>
            {o.label}
          </button>
        ))}
      </div>
    </TweakRow>
  );
}

function TweakSelect({ label, value, options, onChange }) {
  return (
    <TweakRow label={label}>
      <select className="twk-field" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => {
          const v = typeof o === 'object' ? o.value : o;
          const l = typeof o === 'object' ? o.label : o;
          return <option key={v} value={v}>{l}</option>;
        })}
      </select>
    </TweakRow>
  );
}

function TweakText({ label, value, placeholder, onChange }) {
  return (
    <TweakRow label={label}>
      <input className="twk-field" type="text" value={value} placeholder={placeholder}
             onChange={(e) => onChange(e.target.value)} />
    </TweakRow>
  );
}

function TweakNumber({ label, value, min, max, step = 1, unit = '', onChange }) {
  const clamp = (n) => {
    if (min != null && n < min) return min;
    if (max != null && n > max) return max;
    return n;
  };
  const startRef = React.useRef({ x: 0, val: 0 });
  const onScrubStart = (e) => {
    e.preventDefault();
    startRef.current = { x: e.clientX, val: value };
    const decimals = (String(step).split('.')[1] || '').length;
    const move = (ev) => {
      const dx = ev.clientX - startRef.current.x;
      const raw = startRef.current.val + dx * step;
      const snapped = Math.round(raw / step) * step;
      onChange(clamp(Number(snapped.toFixed(decimals))));
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return (
    <div className="twk-num">
      <span className="twk-num-lbl" onPointerDown={onScrubStart}>{label}</span>
      <input type="number" value={value} min={min} max={max} step={step}
             onChange={(e) => onChange(clamp(Number(e.target.value)))} />
      {unit && <span className="twk-num-unit">{unit}</span>}
    </div>
  );
}

// Relative-luminance contrast pick — checkmarks drawn over a swatch need to
// read on both #111 and #fafafa without per-option configuration. Hex input
// only (#rgb / #rrggbb); named or rgb()/hsl() colors fall through to "light".
function __twkIsLight(hex) {
  const h = String(hex).replace('#', '');
  const x = h.length === 3 ? h.replace(/./g, (c) => c + c) : h.padEnd(6, '0');
  const n = parseInt(x.slice(0, 6), 16);
  if (Number.isNaN(n)) return true;
  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  return r * 299 + g * 587 + b * 114 > 148000;
}

const __TwkCheck = ({ light }) => (
  <svg viewBox="0 0 14 14" aria-hidden="true">
    <path d="M3 7.2 5.8 10 11 4.2" fill="none" strokeWidth="2.2"
          strokeLinecap="round" strokeLinejoin="round"
          stroke={light ? 'rgba(0,0,0,.78)' : '#fff'} />
  </svg>
);

// TweakColor — curated color/palette picker. Each option is either a single
// hex string or an array of 1-5 hex strings; the card adapts — a lone color
// renders solid, a palette renders colors[0] as the hero (left ~2/3) with the
// rest stacked in a sharp column on the right. onChange emits the
// option in the shape it was passed (string stays string, array stays array).
// Without options it falls back to the native color input for back-compat.
function TweakColor({ label, value, options, onChange }) {
  if (!options || !options.length) {
    return (
      <div className="twk-row twk-row-h">
        <div className="twk-lbl"><span>{label}</span></div>
        <input type="color" className="twk-swatch" value={value}
               onChange={(e) => onChange(e.target.value)} />
      </div>
    );
  }
  // Native <input type=color> emits lowercase hex per the HTML spec, so
  // compare case-insensitively. String() guards JSON.stringify(undefined),
  // which returns the primitive undefined (no .toLowerCase).
  const key = (o) => String(JSON.stringify(o)).toLowerCase();
  const cur = key(value);
  return (
    <TweakRow label={label}>
      <div className="twk-chips" role="radiogroup">
        {options.map((o, i) => {
          const colors = Array.isArray(o) ? o : [o];
          const [hero, ...rest] = colors;
          const sup = rest.slice(0, 4);
          const on = key(o) === cur;
          return (
            <button key={i} type="button" className="twk-chip" role="radio"
                    aria-checked={on} data-on={on ? '1' : '0'}
                    aria-label={colors.join(', ')} title={colors.join(' · ')}
                    style={{ background: hero }}
                    onClick={() => onChange(o)}>
              {sup.length > 0 && (
                <span>
                  {sup.map((c, j) => <i key={j} style={{ background: c }} />)}
                </span>
              )}
              {on && <__TwkCheck light={__twkIsLight(hero)} />}
            </button>
          );
        })}
      </div>
    </TweakRow>
  );
}

function TweakButton({ label, onClick, secondary = false }) {
  return (
    <button type="button" className={secondary ? 'twk-btn secondary' : 'twk-btn'}
            onClick={onClick}>{label}</button>
  );
}

Object.assign(window, {
  useTweaks, TweaksPanel, TweakSection, TweakRow,
  TweakSlider, TweakToggle, TweakRadio, TweakSelect,
  TweakText, TweakNumber, TweakColor, TweakButton,
});
===== END FILE: tweaks-panel.jsx =====

