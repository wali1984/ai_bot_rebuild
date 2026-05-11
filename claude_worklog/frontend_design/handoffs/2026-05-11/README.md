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

