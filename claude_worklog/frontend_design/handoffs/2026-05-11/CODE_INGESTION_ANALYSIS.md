# CODE_INGESTION_ANALYSIS.md

**Handoff date:** 2026-05-11
**Bundle source:** Claude Design web-chat handoff (HANDOFF_BUNDLE.md, 234,600 bytes, 4,664 lines, 16 file markers)
**Target system:** AI BOT V2 (`/home/wali/Desktop/AI BOT REBUILD/v2/frontend/`)
**Author:** Claude Code

---

## 1. Files in design package

Files extracted under `claude_worklog/frontend_design/handoffs/2026-05-11/`:

| File | Size | Lines | Role |
|---|---:|---:|---|
| `CLAUDE_CODE_PROMPT.md` | 10,080 | 378 | Authoritative implementation contract (source of truth) |
| `README.md` | 10,898 | 161 | Design system overview |
| `index.html` | 12,966 | 390 | Tokens / theme CSS / script load order |
| `app.jsx` | 10,933 | 241 | App shell, sidebar, top bar, blocked-strip marquee |
| `data.jsx` | 12,710 | 171 | **Fixture-only mock data — DESIGN_MOCK_DATA_TO_REMOVE** |
| `primitives.jsx` | 2,135 | 68 | Panel / Chip / StatusDot / Eyebrow / clock hooks |
| `mission-control.jsx` | 22,509 | 492 | Main cockpit composition |
| `signal-explainability.jsx` | 9,984 | 165 | Per-signal feature attribution |
| `risk-control.jsx` | 8,334 | 144 | Risk envelope panel |
| `pages-operate.jsx` | 29,786 | 491 | Symbols / Signals / Executions / Positions / Paper / Replay |
| `pages-inspect.jsx` | 22,170 | 380 | Monitor / Coverage / Script Registry / Trainer Monitor / Audit Ledger |
| `pages-admin.jsx` | 21,700 | 408 | Config / Strategy / Trainer / Orchestrator / Execution / Exchange / Quarantine |
| `pages-ai.jsx` | 15,077 | 257 | Claude Admin / Ollama / Codex Review |
| `pages-system.jsx` | 16,534 | 281 | System Health / Live Readiness / Build Validation / Mobile Readiness |
| `module-placeholder.jsx` | 1,897 | 39 | Module placeholder shell — **must not ship as-is** |
| `tweaks-panel.jsx` | 25,779 | 570 | Design-tool-only theme switcher — **must not ship** |

Raw bundle preserved at `_raw/HANDOFF_BUNDLE.md`.

---

## 2. Routes / components present in design

Routes (window-global page IDs from `app.jsx`):

`mission-control`, `signal-explainability`, `risk-control`, `signals`, `executions`, `positions`, `symbols`, `paper-trading`, `replay`, `trainer-monitor`, `coverage-atlas`, `script-registry`, `monitor-center`, `audit-ledger`, `live-readiness`, `config-admin`, `strategy-admin`, `trainer-admin`, `orchestrator-admin`, `execution-admin`, `claude-admin`, `ollama`, `codex`, `system-health`, `build-validation`, `mobile-readiness`.

(26 page IDs. The design tree is a single-page-app with window-global render, not router-based.)

Components: `App`, `BlockedStrip`, `Sidebar`, `TopBar`, `Telemetry`, `Panel`, `Chip`, `StatusDot`, `Eyebrow`, `MissionControl`, `SignalExplainability`, `RiskControl`, and a `*Page` component per page-id under `pages-*.jsx`. Hooks: `useClock`, `useTicker`, `useTweaks` (theme switcher only).

---

## 3. Mock data present

`data.jsx` ships 171 lines of illustrative numbers used by every page in the prototype, including:

- `NAV` — sidebar nav array with hardcoded `count` and `status` per item.
- `SUBSYSTEMS` — Trainer / Orchestrator / Risk / Execution / Redis / Postgres status rows with fabricated metrics.
- `RISK_RULES` — 12 fake risk-gateway rules with `verdict` / `reason` / `level`.
- `SIGNALS` — 8 fake signal rows with timestamps, `model_id`, `conf`, `feat freshness`, `stop`, `verdict`, `pnl`.
- `POSITIONS` — 6 fake open positions with `entry`, `mark`, `upnl`.
- (Plus tables for executions, scripts, monitors, audit chain, trainer steps, accounts, etc.)

Every `data.jsx` constant is classified `DESIGN_MOCK_DATA_TO_REMOVE`. **Nothing from `data.jsx` is wired into V2.** It is consulted only for IA reference (which columns / fields / chip kinds the design expects).

`app.jsx` `BlockedStrip` also hardcodes marquee strings (e.g. `"policy rev 18"`, `"9 / 14 live-readiness items pending"`, `"audit chain · 1,204,481 links · 0 breaks"`). These too are mock and are **not** lifted; V2's `LiveBlockBanner` keeps its own truth source (`/api/v1/risk/live-readiness`).

---

## 4. Placeholder components present

- `module-placeholder.jsx` — generic dim placeholder rendered by `app.jsx` whenever a page-id does not yet have an implementation. **Per CLAUDE_CODE_PROMPT.md, placeholder-only pages cannot ship.** V2 already replaces this pattern with `PageShell` rendering a visible `cockpit-evidence-gap` block — see Part B.
- `tweaks-panel.jsx` — design-tool-only swatch/theme switcher (570 lines). README explicitly says "do not ship the Tweaks panel into V2 — strip it on ingestion." **Not imported into V2.**

---

## 5. Current V2 components affected

The design package is **not lifted verbatim** into V2. The components below are referenced for visual language only; V2 retains its own implementations:

| Design component | V2 equivalent | Action |
|---|---|---|
| `BlockedStrip` (hatched marquee) | `src/components/banners/LiveBlockBanner.tsx` + `.live-block-banner*` CSS | Extend CSS to add hatched amber surface; keep V2 data source `/api/v1/risk/live-readiness`. |
| `Sidebar` | `src/components/layout/Nav.tsx` | No structural change. V2 uses router-driven nav from `PAGES` registry. |
| `TopBar`, `Telemetry` | (no V2 equivalent) | Defer — telemetry chips would require a runtime payload that does not yet exist (logged in `NEW_PAYLOAD_REQUIREMENTS.md`). |
| `Panel` (bracketed) | (used only inline in V2 pages) | Add `.panel`, `.panel-head`, `.panel-body`, `.bracketed` CSS so existing pages can opt in. |
| `Chip` (kinds: block / warn / ok / paper) | (V2 has `.badge`, `.badge--l4`, `.badge--l5`) | Add `.chip.solid-{block,warn,ok,paper}` utility classes; existing `.badge` stays. |
| `StatusDot` (`.dot`, `.pulse`) | (none) | Add `.dot`, `.pulse` keyframes. |
| `Panel.bracketed` corner brackets | (none) | Add CSS (`.bracketed::before/::after`, `.br-bl`, `.br-br`). |
| `.eyebrow`, `.label-mono`, `.cond`, `.mono`, `.num` typography | (V2 uses system-ui only) | Add IBM Plex Sans + Mono + Sans Condensed via `<link>` preconnect; add utility classes. |
| `.hatch`, `.hatch-strong` | (none) | Add hatched-stripe utility classes. |
| `.grid-bg` 32px grid background | (none) | Add as opt-in utility class. |
| `MissionControl` SVG fallback chart | `src/pages/mission-control/index.tsx` already uses `TradingViewWidget` | **TradingView remains primary in V2.** SVG fallback from the design is not lifted. |
| `data.jsx` | (no V2 import) | Not imported. |
| `module-placeholder.jsx` | `src/components/layout/PageShell.tsx` (renders `cockpit-evidence-gap`) | V2's evidence-gap message already covers this; no copy. |
| `tweaks-panel.jsx` | — | Stripped on ingestion per README. |

---

## 6. Payloads required

V2 already serves runtime/proof payloads from `v2/frontend/public/<feature>/latest/*.json` (~34 feature directories — see `CURRENT_FRONTEND_ROUTE_MAP.md` Section 6).

The design composition introduces a small number of new panel concepts that do not yet have a backing payload — these are written as **requirements only**, not fabricated:

- `topbar_telemetry` — orchestrator latency, gate latency, redis ops/sec.
- `subsystems_strip` — per-subsystem status row (Trainer, Orchestrator, Risk Gateway, Execution, Redis, Postgres) with `metric`, `detail`, `last_event_age`.
- `recent_executions_strip` — last N decisions with chip-style verdict.

Full requirement specs in `NEW_PAYLOAD_REQUIREMENTS.md`.

---

## 7. Missing backend / data contracts

- No payload yet defines `orchestrator_p50_ms`, `gate_p50_ms`, or `redis_ops_per_sec`. Pending a runtime monitor payload extension.
- `data.jsx` shows a `paper_mode` chip and a `live_blocked` chip side-by-side on the TopBar. V2 has `live-block-banner` but no first-class `mode` chip endpoint — current banner derives mode implicitly from `/api/v1/risk/live-readiness.state`. No new contract required if we surface mode from existing payload.
- Signal Explainability per-feature attribution payload: V2 has `decision_explainability_lineage/latest/*.json` — this satisfies the design's feature-attribution panel without a new contract.

---

## 8. Implementation risk

| Risk | Severity | Mitigation |
|---|---|---|
| Lifting `data.jsx` numbers into V2 would present fabricated metrics as live truth. | High | `data.jsx` is **not imported**. `DATA_CONTRACT_ENFORCEMENT.md` rules-out any `DESIGN_MOCK_DATA_TO_REMOVE` from ship. |
| Replacing TradingView with the design's SVG fallback would regress chart quality. | High | TradingView **stays primary** per `CLAUDE_CODE_PROMPT.md` PART D and `TRADINGVIEW_REPLACEMENT_REPORT.md`. |
| Stripping `module-placeholder.jsx` and forgetting evidence-gap copy on a V2 route. | Med | V2's `PageShell` always renders `cockpit-evidence-gap` — no route is silently blank. |
| Shipping `tweaks-panel.jsx`. | Med | Explicitly skipped per README. No import. |
| Breaking the global live-blocked banner by overriding `.live-block-banner` CSS. | High | Style additions are additive (new utility classes); existing `.live-block-banner*` rules are preserved. |
| Theme switcher introducing inconsistent state. | Med | Design tokens for `light` / `terminal` themes are added as inert CSS variables only; **no `data-theme` switcher is wired up** in this pass — token namespace is reserved for a future-controlled switch. |
| Loading IBM Plex from Google Fonts adds 3rd-party request. | Low | Acceptable; matches design fidelity. PWA service-worker can cache. |
| Hatched amber marquee could be mistaken for the live-blocked state. | Low | Hatched stripes only apply to the live-blocked banner when `state === 'blocked'`; other states (`pending`, `active`) keep solid amber/green. |
| Lifting the design's "policy rev 18" / "9/14 pending" hardcoded marquee strings. | High | **Not lifted.** V2's banner only renders text derived from `/api/v1/risk/live-readiness`. |
