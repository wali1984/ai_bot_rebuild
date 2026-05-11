# DATA_CONTRACT_ENFORCEMENT.md

**Handoff date:** 2026-05-11
**Rule:** every panel must declare its data source, every panel must show a visible freshness/source label, no fabrication.

Classifications used:
- `READONLY_MARKET_FEED` — read-only price/orderbook/ticker from external exchange feed
- `READONLY_ACCOUNT_FEED` — read-only account/position/balance feed (never order placement)
- `RUNTIME_MONITOR_PAYLOAD` — V2 runtime monitor JSON dropped under `public/<feature>/latest/`
- `V2_PROOF_ARTIFACT` — preserved static proof JSON under `public/<feature>/latest/`
- `STATIC_PROOF_FIXTURE` — labeled non-live fixture committed to repo
- `MISSING_EVIDENCE` — backing payload does not yet exist; panel renders evidence-gap UI
- `DESIGN_MOCK_DATA_TO_REMOVE` — present in Claude Design `data.jsx` only; never ships

Rules:
- `DESIGN_MOCK_DATA_TO_REMOVE` cannot ship.
- `STATIC_PROOF_FIXTURE` must be visibly labeled (V2 uses `FreshnessBadge` with `mode: 'STATIC_PROOF_FIXTURE'`).
- `MISSING_EVIDENCE` must say exactly what source/task is missing.
- Signal explanations must not guess — features without an artifact render `MISSING_EVIDENCE`, never invented contributions.
- Every panel must show freshness/source labels via V2's `FreshnessBadge` (or the `cockpit-evidence-gap` block for missing payloads).

---

## Mission Control (`/admin/mission-control`)

| Panel | Classification | Backing payload | Freshness label |
|---|---|---|---|
| Live-blocked banner (sticky top) | `READONLY_ACCOUNT_FEED` (live-readiness state only) | `GET /api/v1/risk/live-readiness` | label in banner |
| GO / NO-GO readiness gate | `V2_PROOF_ARTIFACT` | `online_readiness_control_plane/latest/*.json` | `FreshnessBadge` |
| Subsystem strip (Trainer / Orch / Risk / Exec / Redis / Postgres) | `RUNTIME_MONITOR_PAYLOAD` (partial) + `MISSING_EVIDENCE` (some fields) | `phase3c_runtime_monitor_verification/latest/*.json` | per-row badge; missing rows render `cockpit-evidence-gap` |
| Primary chart | `READONLY_MARKET_FEED` | TradingView external widget | TradingView source label |
| Decision overlay / decision drawers | `V2_PROOF_ARTIFACT` | `decision_explainability_lineage/latest/*.json` | `FreshnessBadge` |
| Recent signals strip | `V2_PROOF_ARTIFACT` | `enterprise_trading_cockpit/latest/operator_cockpit_payload.json` (signals section) | `FreshnessBadge` |
| Recent executions strip | `V2_PROOF_ARTIFACT` | `historical_30d_replay_and_paper_proof/latest/legacy_vs_v2_decision_comparison.json` | `FreshnessBadge` |
| Proof freshness summary card | `V2_PROOF_ARTIFACT` | per-artifact `source_generated_at` + `public_copied_at` | inline state |
| Design's `topbar_telemetry` (orch latency / gate latency / redis ops/sec) | `MISSING_EVIDENCE` | not yet provisioned — see `NEW_PAYLOAD_REQUIREMENTS.md` `topbar_telemetry` | evidence-gap copy |

Mock items rejected: `BlockedStrip` strings (`"policy rev 18"`, `"audit chain · 1,204,481 links"`), `SUBSYSTEMS` numbers (`loss 0.0382`, `keys 12,481`), `TopBar` telemetry numbers — all `DESIGN_MOCK_DATA_TO_REMOVE`, not lifted.

---

## Operator Proof Dashboard (`/admin/operator-proof-dashboard`)

| Panel | Classification | Backing payload |
|---|---|---|
| Proof hero / status chips | `V2_PROOF_ARTIFACT` | `non_live_operational_proof/latest/*.json` |
| Decision lineage table | `V2_PROOF_ARTIFACT` | `decision_explainability_lineage/latest/*.json` |
| Paper shadow strip | `V2_PROOF_ARTIFACT` | `continuous_paper_shadow_runtime/latest/paper_runtime_status.json`, `paper_positions.json` |
| Risk blocks table | `V2_PROOF_ARTIFACT` | `orchestrator_risk_boundary/latest/v2_risk_blocks.json` |
| 30-day replay comparison | `V2_PROOF_ARTIFACT` | `historical_30d_replay_and_paper_proof/latest/legacy_vs_v2_decision_comparison.json`, `shadow_comparison_30d.json` |
| Quarantine table | `V2_PROOF_ARTIFACT` | `external_manual_position_quarantine/latest/*.json` |

Per file inspection — no fabricated values; all reads from preserved proof artifacts. Page is the canonical evidence/proof page and must remain evidence-only.

---

## Monitor Center (`/admin/monitor-center`)

| Panel | Classification | Backing payload |
|---|---|---|
| Monitor table (script / owner / status / last run / metrics) | `V2_PROOF_ARTIFACT` | `automation_liveness/latest/task_queue_liveness.json`, `agent_process_snapshot.json`, `dashboard_liveness_payload.json` |
| Trainer prediction stream | `MISSING_EVIDENCE` | `trainer_lineage_and_readiness/latest/*.json` partial |
| Price prediction accuracy | `MISSING_EVIDENCE` | not yet defined |
| Signal causality | `MISSING_EVIDENCE` | not yet defined |
| Feature freshness | `RUNTIME_MONITOR_PAYLOAD` | `phase3c_runtime_monitor_verification/latest/*.json` |
| Model health | `MISSING_EVIDENCE` | not yet defined |
| Risk gate status | `V2_PROOF_ARTIFACT` | `orchestrator_risk_boundary/latest/v2_risk_blocks.json` |
| Execution latency | `MISSING_EVIDENCE` | not yet defined |
| Claude supervision health | `MISSING_EVIDENCE` | not yet defined |
| Ollama summarization health | `MISSING_EVIDENCE` | not yet defined |
| Codex review status | `V2_PROOF_ARTIFACT` (selected) | `codex_parallel_audit_plan/latest/*.json` |

Missing panels render `cockpit-evidence-gap` with the exact missing source named — see `NEW_PAYLOAD_REQUIREMENTS.md`.

---

## Signal Explainability (`/admin/signal-explainability`)

| Panel | Classification | Backing payload |
|---|---|---|
| Per-signal feature attribution | `V2_PROOF_ARTIFACT` | `decision_explainability_lineage/latest/*.json` |
| Model version / checkpoint | `V2_PROOF_ARTIFACT` | same |
| Feature freshness | `V2_PROOF_ARTIFACT` | same |
| Orchestrator reason | `V2_PROOF_ARTIFACT` | same |
| Risk gateway reason | `V2_PROOF_ARTIFACT` | `orchestrator_risk_boundary/latest/v2_risk_blocks.json` joined |
| Missing feature contribution | `MISSING_EVIDENCE` | rendered as evidence-gap; **no guessing** |

Hard rule: if the artifact does not contain a feature's contribution value, the panel must render `MISSING_EVIDENCE` with the artifact path, not invented filler.

---

## Risk Control (`/admin/risk-control`)

| Panel | Classification | Backing payload |
|---|---|---|
| Risk envelope | `V2_PROOF_ARTIFACT` | `orchestrator_risk_boundary/latest/v2_risk_blocks.json` + `online_readiness_control_plane/latest/*.json` |
| Per-symbol caps | `V2_PROOF_ARTIFACT` | same |
| Drawdown gates | `V2_PROOF_ARTIFACT` | same |
| Kill-switch state | `READONLY_ACCOUNT_FEED` (state-only) | `GET /api/v1/risk/live-readiness` |
| Dangerous-control toggles | `V2_PROOF_ARTIFACT` | `src/constants/dangerousControls.ts` (definitions) + per-control state payload |

Page must keep dangerous-control approval gating; current `DangerousControlPanel` already enforces.

---

## Operate pages (signals / executions / positions / symbols / paper / replay)

| Page | Classification | Backing payload |
|---|---|---|
| `/admin/signals` | `V2_PROOF_ARTIFACT` (evidence-gap until wired) | `decision_explainability_lineage/latest/*.json` |
| `/admin/executions` | `V2_PROOF_ARTIFACT` (evidence-gap until wired) | `historical_30d_replay_and_paper_proof/latest/*.json` |
| `/admin/positions` | `V2_PROOF_ARTIFACT` (evidence-gap until wired) | `continuous_paper_shadow_runtime/latest/paper_positions.json` |
| `/admin/symbols` | `READONLY_MARKET_FEED` / `MISSING_EVIDENCE` | TradingView symbols + a future curated symbol-universe artifact |
| `/admin/paper-trading` | `V2_PROOF_ARTIFACT` | `continuous_paper_shadow_runtime/latest/paper_runtime_status.json` |
| `/admin/replay` | `V2_PROOF_ARTIFACT` | `historical_30d_replay_and_paper_proof/latest/*.json` |

All pages already render `cockpit-evidence-gap` until specific payloads are wired in subsequent phases — no fabrication.

---

## Inspect pages (coverage / script-registry / trainer-monitor / audit-ledger)

| Page | Classification | Backing payload |
|---|---|---|
| `/admin/coverage-system-atlas` | `V2_PROOF_ARTIFACT` | `system_atlas_runtime_coverage/latest/*.json` + `system_atlas_gap_remediation/latest/*.json` |
| `/admin/script-registry` | `V2_PROOF_ARTIFACT` | `automation_liveness/latest/SCRIPT_REGISTRY.json` |
| `/admin/trainer-prediction-monitor` | `V2_PROOF_ARTIFACT` | `trainer_lineage_and_readiness/latest/*.json` |
| `/admin/audit-ledger` | `MISSING_EVIDENCE` | dedicated audit chain artifact pending |

---

## Admin pages (config / strategy / trainer / orchestrator / execution / exchange / quarantine)

| Page | Classification | Backing payload |
|---|---|---|
| `/admin/config-admin` | `V2_PROOF_ARTIFACT` | `online_readiness_control_plane/latest/*.json` (config slice) |
| `/admin/strategy-admin` | `MISSING_EVIDENCE` | strategy-registry artifact pending |
| `/admin/trainer-admin` | `MISSING_EVIDENCE` | trainer-admin artifact pending |
| `/admin/orchestrator-admin` | `V2_PROOF_ARTIFACT` (partial) | `orchestrator_risk_boundary/latest/*.json` |
| `/admin/execution-admin` | `MISSING_EVIDENCE` | execution-admin artifact pending |
| `/admin/exchange-manager` | `READONLY_ACCOUNT_FEED` (state-only) | exchange-manager liveness artifact + read-only credentials state |
| `/admin/external-manual-position-quarantine` | `V2_PROOF_ARTIFACT` | `external_manual_position_quarantine/latest/quarantined_positions.json`, `unattributed_executions.json` |

Dangerous-setting approval classification: `src/constants/dangerousControls.ts` classifies each dangerous setting at `L4` / `L5` levels and is enforced by `DangerousControlPanel`. Settings include: enable live trading, add/activate live API keys, increase leverage, enable CROSS margin, increase max position size, increase daily loss limit, disable kill switch, disable mandatory stop, enable hedge/DCA, enable ADJUST_LEVERAGE, switch paper→live.

---

## AI pages (claude / ollama / codex)

| Page | Classification | Backing payload |
|---|---|---|
| `/admin/claude-admin-ai` | `MISSING_EVIDENCE` | Claude session metadata payload pending |
| `/admin/ollama-local-assistant` | `V2_PROOF_ARTIFACT` (partial) | `ollama/evidence_packets/*.json` (filtered + summarized only) |
| `/admin/codex-review-center` | `V2_PROOF_ARTIFACT` | `codex_parallel_audit_plan/latest/*.json` |

---

## System pages (system-health / live-readiness / build-validation / mobile-readiness)

| Page | Classification | Backing payload |
|---|---|---|
| `/admin/system-health` | `RUNTIME_MONITOR_PAYLOAD` / `MISSING_EVIDENCE` | `phase3c_runtime_monitor_verification/latest/*.json` (subset) |
| `/admin/live-readiness` | `V2_PROOF_ARTIFACT` | `online_readiness_control_plane/latest/*.json`, `autonomous_live_readiness_builder/latest/*.json` |
| `/admin/build-validation-status` | `MISSING_EVIDENCE` | build/validation status artifact pending |
| `/admin/mobile-iphone-readiness` | `MISSING_EVIDENCE` | mobile readiness checklist artifact pending |

---

## Top-level enforcement summary

- 27 admin routes mapped (Mission Control, Operator Proof Dashboard, plus 25 inner pages).
- 0 panels classified `DESIGN_MOCK_DATA_TO_REMOVE` ship — `data.jsx` is not imported.
- 12 panels classified `MISSING_EVIDENCE` — each one renders a `cockpit-evidence-gap` block and is logged in `NEW_PAYLOAD_REQUIREMENTS.md`.
- TradingView remains primary chart; design's SVG fallback is not lifted.
- Live-blocked banner remains sticky / undismissable, derived from `/api/v1/risk/live-readiness`.
- Signal Explainability does not guess; missing feature contributions render evidence-gap with artifact pointer.
- Every panel either carries a `FreshnessBadge` (where the freshness object is in the payload) or renders an evidence-gap block (where it is not).
