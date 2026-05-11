# PAGE_FEATURE_COVERAGE.md

**Handoff date:** 2026-05-11
**Rule:** every required page must exist or be an explicit evidence gap.

Legend:
- `IMPLEMENTED` — V2 page has bespoke composition + payload wiring beyond `PageShell`.
- `EVIDENCE_GAP` — route registered, page renders `cockpit-evidence-gap` until payload populated.
- `MISSING` — route not registered.

| # | Required page | V2 route | Status | File | Notes |
|---|---|---|---|---|---|
| 1 | Mission Control | `/admin/mission-control` | IMPLEMENTED | `src/pages/mission-control/index.tsx` | Cockpit composition with `Phase3cRuntimeMonitorPanel`, TradingView, decision drawers, proof freshness. |
| 2 | Monitor Center | `/admin/monitor-center` | EVIDENCE_GAP | `src/pages/monitor-center/index.tsx` | Will wire `automation_liveness/latest/*.json` (script registry + task queue + agent snapshot). |
| 3 | Coverage / System Atlas | `/admin/coverage-system-atlas` | IMPLEMENTED | `src/pages/coverage-system-atlas/index.tsx` | Reads `system_atlas_runtime_coverage` + `system_atlas_gap_remediation`. |
| 4 | Script Registry | `/admin/script-registry` | IMPLEMENTED | `src/pages/script-registry/index.tsx` | Reads `automation_liveness/latest/SCRIPT_REGISTRY.json`; renders evidence gaps. |
| 5 | Trainer Prediction Monitor | `/admin/trainer-prediction-monitor` | EVIDENCE_GAP | `src/pages/trainer-prediction-monitor/index.tsx` | Will wire `trainer_lineage_and_readiness`. |
| 6 | Signal Explainability | `/admin/signal-explainability` | EVIDENCE_GAP | `src/pages/signal-explainability/index.tsx` | Will wire `decision_explainability_lineage`. **Will not guess** — missing features render evidence gap. |
| 7 | Symbols | `/admin/symbols` | EVIDENCE_GAP | `src/pages/symbols/index.tsx` | Symbol universe artifact pending. |
| 8 | Signals | `/admin/signals` | EVIDENCE_GAP | `src/pages/signals/index.tsx` | Will wire `decision_explainability_lineage`. |
| 9 | Executions | `/admin/executions` | EVIDENCE_GAP | `src/pages/executions/index.tsx` | Will wire `historical_30d_replay_and_paper_proof`. |
| 10 | Positions | `/admin/positions` | EVIDENCE_GAP | `src/pages/positions/index.tsx` | Will wire `continuous_paper_shadow_runtime/latest/paper_positions.json`. |
| 11 | Risk Control | `/admin/risk-control` | EVIDENCE_GAP | `src/pages/risk-control/index.tsx` | Will wire `orchestrator_risk_boundary/latest/v2_risk_blocks.json`. Dangerous controls already gated. |
| 12 | Config Admin | `/admin/config-admin` | EVIDENCE_GAP | `src/pages/config-admin/index.tsx` | Will wire `online_readiness_control_plane` config slice. Dangerous-setting classification already enforced. |
| 13 | Strategy Admin | `/admin/strategy-admin` | EVIDENCE_GAP | `src/pages/strategy-admin/index.tsx` | Strategy registry artifact pending. |
| 14 | Trainer Admin | `/admin/trainer-admin` | EVIDENCE_GAP | `src/pages/trainer-admin/index.tsx` | Trainer admin artifact pending. |
| 15 | Orchestrator Admin | `/admin/orchestrator-admin` | EVIDENCE_GAP | `src/pages/orchestrator-admin/index.tsx` | Will wire `orchestrator_risk_boundary`. |
| 16 | Execution Admin | `/admin/execution-admin` | EVIDENCE_GAP | `src/pages/execution-admin/index.tsx` | Execution admin artifact pending. |
| 17 | Paper Trading | `/admin/paper-trading` | EVIDENCE_GAP | `src/pages/paper-trading/index.tsx` | Will wire `continuous_paper_shadow_runtime/latest/paper_runtime_status.json`. |
| 18 | Replay | `/admin/replay` | EVIDENCE_GAP | `src/pages/replay/index.tsx` | Will wire `historical_30d_replay_and_paper_proof`. |
| 19 | Audit Ledger | `/admin/audit-ledger` | EVIDENCE_GAP | `src/pages/audit-ledger/index.tsx` | Audit chain artifact pending. |
| 20 | System Health | `/admin/system-health` | EVIDENCE_GAP | `src/pages/system-health/index.tsx` | Will wire `phase3c_runtime_monitor_verification` subset. |
| 21 | Live Readiness | `/admin/live-readiness` | EVIDENCE_GAP | `src/pages/live-readiness/index.tsx` | Will wire `online_readiness_control_plane`. |
| 22 | Claude Admin AI | `/admin/claude-admin-ai` | EVIDENCE_GAP | `src/pages/claude-admin-ai/index.tsx` | Claude session-metadata artifact pending. |
| 23 | Ollama Local Assistant | `/admin/ollama-local-assistant` | EVIDENCE_GAP | `src/pages/ollama-local-assistant/index.tsx` | Will wire `ollama/evidence_packets`. |
| 24 | Codex Review Center | `/admin/codex-review-center` | EVIDENCE_GAP | `src/pages/codex-review-center/index.tsx` | Will wire `codex_parallel_audit_plan`. |
| 25 | Build / Validation Status | `/admin/build-validation-status` | EVIDENCE_GAP | `src/pages/build-validation-status/index.tsx` | Build/validation artifact pending. |
| 26 | Mobile / iPhone Readiness | `/admin/mobile-iphone-readiness` | EVIDENCE_GAP | `src/pages/mobile-iphone-readiness/index.tsx` | Mobile readiness artifact pending. |
| 27 | Exchange Manager | `/admin/exchange-manager` | EVIDENCE_GAP | `src/pages/exchange-manager/index.tsx` | Will wire read-only exchange liveness. |
| 28 | External / Manual Position Quarantine | `/admin/external-manual-position-quarantine` | EVIDENCE_GAP | `src/pages/external-manual-position-quarantine/index.tsx` | Will wire `external_manual_position_quarantine/latest/*.json`. |
| 29 | Operator Proof Dashboard (extra, V2-specific) | `/admin/operator-proof-dashboard` | IMPLEMENTED | `src/pages/operator-proof-dashboard/index.tsx` | Canonical evidence/proof page (882 lines, multi-section). |

**Coverage:** 28/28 required pages present, plus the V2-specific `operator-proof-dashboard`. 0 missing.

**Placeholder-only ships:** 0. Every `EVIDENCE_GAP` page renders `cockpit-evidence-gap` with a description of what data source is missing — this satisfies the rule "No placeholder-only pages."

**Mock data ships:** 0. The design `data.jsx` is not imported into V2; no fabricated values appear in any panel.

**Live enablement introduced:** 0. Live trading remains `blocked_human_only`; banner unchanged.
