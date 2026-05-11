# CURRENT_FRONTEND_ROUTE_MAP.md

**Handoff date:** 2026-05-11
**V2 stack:** Vite 5.4.8 + TypeScript 5.6.2 + React 18.3.1 + react-router-dom 6.26.2
**Router:** `v2/frontend/src/router.tsx` (centralized via `src/pages/registry.ts`)
**Shell:** `v2/frontend/src/components/layout/AdminShell.tsx`
**Live-blocked banner:** `v2/frontend/src/components/banners/LiveBlockBanner.tsx` (sticky, undismissable, mounted in `AdminShell`)
**Style system:** vanilla CSS in `v2/frontend/src/styles.css` (914 lines, design tokens on `:root`)
**Chart:** `v2/frontend/src/components/charts/TradingViewWidget.tsx` (TradingView primary, used by `ChartPanel` in `cockpitComponents.tsx`)

---

## 1. Design-page → V2-route mapping

| Design page-id | V2 route | V2 component file | Status |
|---|---|---|---|
| `mission-control` | `/admin/mission-control` | `src/pages/mission-control/index.tsx` | implemented; uses real payloads |
| `signal-explainability` | `/admin/signal-explainability` | `src/pages/signal-explainability/index.tsx` | route exists; payload-backed; renders evidence gap until payload populated |
| `risk-control` | `/admin/risk-control` | `src/pages/risk-control/index.tsx` | route exists; `PageShell` evidence-gap |
| `signals` | `/admin/signals` | `src/pages/signals/index.tsx` | route exists; `PageShell` evidence-gap |
| `executions` | `/admin/executions` | `src/pages/executions/index.tsx` | route exists; `PageShell` evidence-gap |
| `positions` | `/admin/positions` | `src/pages/positions/index.tsx` | route exists; `PageShell` evidence-gap |
| `symbols` | `/admin/symbols` | `src/pages/symbols/index.tsx` | route exists; `PageShell` evidence-gap |
| `paper-trading` | `/admin/paper-trading` | `src/pages/paper-trading/index.tsx` | route exists; `PageShell` evidence-gap |
| `replay` | `/admin/replay` | `src/pages/replay/index.tsx` | route exists; `PageShell` evidence-gap |
| `trainer-monitor` | `/admin/trainer-prediction-monitor` | `src/pages/trainer-prediction-monitor/index.tsx` | route exists |
| `coverage-atlas` | `/admin/coverage-system-atlas` | `src/pages/coverage-system-atlas/index.tsx` | implemented; renders evidence gaps |
| `script-registry` | `/admin/script-registry` | `src/pages/script-registry/index.tsx` | implemented; renders evidence gaps |
| `monitor-center` | `/admin/monitor-center` | `src/pages/monitor-center/index.tsx` | route exists |
| `audit-ledger` | `/admin/audit-ledger` | `src/pages/audit-ledger/index.tsx` | route exists; `PageShell` evidence-gap |
| `live-readiness` | `/admin/live-readiness` | `src/pages/live-readiness/index.tsx` | route exists; `PageShell` evidence-gap |
| `config-admin` | `/admin/config-admin` | `src/pages/config-admin/index.tsx` | route exists |
| `strategy-admin` | `/admin/strategy-admin` | `src/pages/strategy-admin/index.tsx` | route exists; `PageShell` evidence-gap |
| `trainer-admin` | `/admin/trainer-admin` | `src/pages/trainer-admin/index.tsx` | route exists; `PageShell` evidence-gap |
| `orchestrator-admin` | `/admin/orchestrator-admin` | `src/pages/orchestrator-admin/index.tsx` | route exists; `PageShell` evidence-gap |
| `execution-admin` | `/admin/execution-admin` | `src/pages/execution-admin/index.tsx` | route exists; `PageShell` evidence-gap |
| `claude-admin` | `/admin/claude-admin-ai` | `src/pages/claude-admin-ai/index.tsx` | route exists; `PageShell` evidence-gap |
| `ollama` | `/admin/ollama-local-assistant` | `src/pages/ollama-local-assistant/index.tsx` | route exists; `PageShell` evidence-gap |
| `codex` | `/admin/codex-review-center` | `src/pages/codex-review-center/index.tsx` | route exists; `PageShell` evidence-gap |
| `system-health` | `/admin/system-health` | `src/pages/system-health/index.tsx` | route exists; `PageShell` evidence-gap |
| `build-validation` | `/admin/build-validation-status` | `src/pages/build-validation-status/index.tsx` | route exists; `PageShell` evidence-gap |
| `mobile-readiness` | `/admin/mobile-iphone-readiness` | `src/pages/mobile-iphone-readiness/index.tsx` | route exists; `PageShell` evidence-gap |
| (design has no separate page) | `/admin/operator-proof-dashboard` | `src/pages/operator-proof-dashboard/index.tsx` (882 lines) | implemented; canonical proof / evidence page |
| (design has no separate page) | `/admin/exchange-manager` | `src/pages/exchange-manager/index.tsx` | route exists |
| (design has no separate page) | `/admin/external-manual-position-quarantine` | `src/pages/external-manual-position-quarantine/index.tsx` | route exists |

**Required main route:** `/admin/mission-control?role=admin` — present.
**Required evidence route:** `/admin/operator-proof-dashboard?role=admin` — present.

Every design page-id maps to a real V2 route. No design-driven routes need to be added.

---

## 2. Design-component → V2-component mapping

| Design component | V2 destination | Plan |
|---|---|---|
| `Panel` (incl. `bracketed`) | `src/pages/cockpitComponents.tsx` `<Panel>` already exists; CSS adds `.panel`, `.panel-head`, `.panel-title`, `.panel-body`, `.bracketed` | extend CSS only |
| `Chip` (`solid-block` / `solid-warn` / `solid-ok` / `solid-paper`) | new CSS utility classes in `styles.css` | extend CSS only |
| `StatusDot` (`.dot`, `.pulse`) | new CSS utility classes | extend CSS only |
| `Eyebrow` / `.eyebrow`, `.label-mono`, `.cond`, `.mono`, `.num` | new CSS utility classes | extend CSS only |
| `BlockedStrip` (hatched marquee) | `LiveBlockBanner` already renders the global banner; add `.live-block-banner--hatched` modifier when state == `blocked` | extend CSS only |
| `Sidebar` | `src/components/layout/Nav.tsx` | no change |
| `TopBar`, `Telemetry` | no current V2 component | not implemented this pass (requires runtime telemetry payload — see PART G) |
| `MissionControl` SVG chart | replaced by `TradingViewWidget` in V2 already | TradingView stays primary |
| `RiskControl` panel composition | `src/pages/risk-control/index.tsx` | reads design layout only; data wiring deferred to risk-control payload work |
| `SignalExplainability` panel | `src/pages/signal-explainability/index.tsx` | reads design layout only; backed by `decision_explainability_lineage/latest/*.json` when populated |
| `module-placeholder.jsx` | `src/components/layout/PageShell.tsx` already renders `cockpit-evidence-gap` | no copy |
| `tweaks-panel.jsx` | — | stripped per README |

---

## 3. Design-data → V2 payload mapping

All `data.jsx` constants are classified `DESIGN_MOCK_DATA_TO_REMOVE`. **None ships.**

| Design data | V2 payload (read-only) | Source |
|---|---|---|
| `NAV` | Router registry `src/pages/registry.ts` (static, code-defined) | code |
| `SUBSYSTEMS` | `RUNTIME_MONITOR_PAYLOAD` — `phase3c_runtime_monitor_verification/latest/*.json` partially covers Trainer/Orchestrator/Risk/Redis | proof artifact |
| `RISK_RULES` | `orchestrator_risk_boundary/latest/v2_risk_blocks.json` (subset) | proof artifact |
| `SIGNALS` | `decision_explainability_lineage/latest/*.json` and `historical_30d_replay_and_paper_proof/latest/*.json` | proof artifact |
| `POSITIONS` | `continuous_paper_shadow_runtime/latest/paper_positions.json` (paper mode) | proof artifact |
| `EXECUTIONS` | `historical_30d_replay_and_paper_proof/latest/legacy_vs_v2_decision_comparison.json` | proof artifact |
| `SCRIPTS` | `script-registry` page reads `automation_liveness/latest/SCRIPT_REGISTRY.json` | proof artifact |
| `MONITORS` | `automation_liveness/latest/task_queue_liveness.json` + `agent_process_snapshot.json` | proof artifact |
| `AUDIT_CHAIN` | `audit-ledger` route — currently evidence gap, payload requirement filed | MISSING_EVIDENCE |
| `TRAINER` predictions | `trainer_lineage_and_readiness/latest/*.json` | proof artifact |
| `topbar_telemetry` (latency, ops/sec) | no V2 payload | MISSING_EVIDENCE — see PART G |

---

## 4. Design-mock → real-payload-or-gap (decision table)

| Design mock | Decision |
|---|---|
| `NAV[].count` (e.g. `signals: 47`, `positions: 6`) | **REMOVE.** V2 nav is static; counts come from page-level payloads at render time, not the nav. |
| `SUBSYSTEMS` rows with fabricated `loss 0.0382`, `step 184,201`, `keys 12,481` | **REMOVE.** No V2 panel surfaces this exact composition yet. Future runtime-monitor extension required. |
| `BlockedStrip` strings: `"policy rev 18"`, `"9 / 14 pending"`, `"audit chain · 1,204,481 links"` | **REMOVE.** V2 banner derives from `/api/v1/risk/live-readiness` only. |
| `TopBar` telemetry: `orch latency 0.42ms`, `gate latency 0.84ms`, `redis ops/s 9.4` | **EVIDENCE GAP** — defer until runtime monitor publishes `topbar_telemetry.json`. |
| `SIGNALS` table with `pnl +0.34%` | **EVIDENCE GAP** — signals page wires to real lineage payload when populated. |
| `POSITIONS` rows with fabricated `entry`, `mark`, `upnl` | **EVIDENCE GAP** — positions page wires to `paper_positions.json` when wired up. |
| `RISK_RULES` reasons (e.g. `"dedup window 24h"`) | **EVIDENCE GAP** — risk-control page wires to `v2_risk_blocks.json` when wired up. |
| `data.jsx` static fixture set (entire file) | **REMOVE — not imported.** |

---

## 5. Design-placeholder → V2 disposition

| Design placeholder | V2 disposition |
|---|---|
| `module-placeholder.jsx` (generic dim "soon" page) | **REMOVED** from V2 — `PageShell` renders a labeled `cockpit-evidence-gap` block instead. Every V2 route reaches a visible message; none ship blank. |
| `tweaks-panel.jsx` (570-line theme switcher widget) | **STRIPPED.** Not imported into V2. Future theme switching is a separate piece of work and not part of this handoff. |

---

## 6. V2 public payload directory (proof artifacts)

`v2/frontend/public/` contains 34 feature directories; each has a `latest/` subfolder with one or more JSON proof artifacts. Notable entries (used by Mission Control / Operator Proof Dashboard today):

- `phase3c_runtime_monitor_verification/latest/*.json` — runtime monitor coverage
- `orchestrator_risk_boundary/latest/v2_risk_blocks.json` — risk-gateway block table
- `decision_explainability_lineage/latest/*.json` — per-decision feature lineage
- `historical_30d_replay_and_paper_proof/latest/legacy_vs_v2_decision_comparison.json`
- `continuous_paper_shadow_runtime/latest/paper_runtime_status.json`, `paper_positions.json`
- `automation_liveness/latest/SCRIPT_REGISTRY.json`, `task_queue_liveness.json`, `agent_process_snapshot.json`, `dashboard_liveness_payload.json`
- `enterprise_trading_cockpit/latest/operator_cockpit_payload.json`
- `external_manual_position_quarantine/latest/quarantined_positions.json`, `unattributed_executions.json`
- `system_atlas_runtime_coverage/latest/*.json`
- `redis_memory_pressure_remediation/latest/*.json`, `redis_safe_trim_packet/latest/*.json`, `redis_human_approval/latest/*.json`
- `online_readiness_control_plane/latest/*.json`
- `autonomous_governor/latest/*.json`
- `mobile-iphone-readiness` / `build-validation-status` / `system-health` / `live-readiness`: payloads not yet under a dedicated directory — handled as evidence gap until provisioned.

`v2/frontend/public/manifest.webmanifest` and `service-worker.js` provide PWA scaffolding.

---

## 7. Required route confirmations

| Required route (from CLAUDE_CODE_PROMPT.md PART H) | Exists? | File |
|---|---|---|
| `/admin/mission-control?role=admin` | yes | `src/pages/mission-control/index.tsx` |
| `/admin/operator-proof-dashboard?role=admin` | yes | `src/pages/operator-proof-dashboard/index.tsx` |
| `/admin/monitor-center?role=admin` | yes | `src/pages/monitor-center/index.tsx` |
| `/admin/trainer-prediction-monitor?role=admin` | yes | `src/pages/trainer-prediction-monitor/index.tsx` |
| `/admin/signal-explainability?role=admin` | yes | `src/pages/signal-explainability/index.tsx` |
| `/admin/config-admin?role=admin` | yes | `src/pages/config-admin/index.tsx` |
| `/admin/exchange-manager?role=admin` | yes | `src/pages/exchange-manager/index.tsx` |
| `/admin/mobile-iphone-readiness?role=admin` | yes | `src/pages/mobile-iphone-readiness/index.tsx` |
| `/admin/build-validation-status?role=admin` | yes | `src/pages/build-validation-status/index.tsx` |

All required smoke routes resolve.
