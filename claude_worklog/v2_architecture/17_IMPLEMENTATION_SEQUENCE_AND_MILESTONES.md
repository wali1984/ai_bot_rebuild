# 17 Implementation Sequence and Milestones

## 1. Purpose

This document is the canonical sequence and gating contract for the V2 build. It enumerates the milestones, the objective gate evidence required to enter each milestone, the validation artifacts that must be produced inside each milestone, and the governance level that approves each transition. It is the document the V2 build supervisor reads when deciding whether the next milestone may begin.

It does not authorize V2 code. It defines the conditions under which V2 code may begin to be planned, scaffolded, and shipped. The default for every gate is BLOCKED until the listed evidence is materialized and verified.

## 2. Hard constraints (override every milestone)

- Do not start with live execution. Live trading is blocked by default per `CLAUDE.md`. No milestone in this sequence unblocks live trading; live trading has its own separate gate (Live Readiness, milestone N) and its own separate human approval (milestone O).
- Do not mutate the legacy bot at `/home/wali/Desktop/AI BOT`. Read-only inspection only.
- Do not write the legacy Redis instance. The legacy Redis namespace is read-only for V2; V2 uses its own `V2_REDIS_PREFIX`.
- Do not restart legacy services (trainer, trader, orchestrator, Redis, VPN). Recovery is human-gated per the Protected Runtime Policy.
- Do not Dockerize the trainer or upgrade trainer-side packages. The protected ML runtime is preserved.
- Do not skip the objective gate evidence in §3 even under schedule pressure. The Completeness Override applies.
- Every milestone produces a validation artifact under `claude_worklog/` and a corresponding evidence packet under `claude_worklog/.../evidence_packets/` or `raw_evidence/`. Summaries are not evidence; raw evidence pointers are required per the Evidence Integrity Rule.

## 3. Pre-scaffold objective gate evidence (required before milestone B)

V2 scaffold planning (milestone B) MUST NOT begin until every item in the table below resolves to a present, verified artifact. The supervisor's pre-dispatch check refuses any milestone-B task whose `gate_evidence_ref` does not resolve to all four closure files AND a passing Codex rerun.

| # | Gate item | Required artifact | Closure document | Resolution status |
|---|-----------|-------------------|------------------|-------------------|
| 1 | Database lineage chain enforceable end-to-end | `claude_worklog/v2_architecture/03_DATABASE_SCHEMA.md` updated with NOT NULL FKs, `ON DELETE/UPDATE RESTRICT`, CHECK constraints, audit indexes for the six-ID chain `feature_snapshot_id -> prediction_id -> signal_id -> decision_id -> risk_decision_id -> execution_intent_id` | `claude_worklog/v2_architecture_remediation/12A_DATABASE_LINEAGE_CLOSURE.md` | CLOSED at architecture-text level |
| 2 | API lineage carriage and rejection classes | `claude_worklog/v2_architecture/05_API_CONTRACTS.md` §1.3, §2.3, §3.2/§3.3, §3.4, §6, §9, §13 — canonical `lineage` block, seven `lineage.*` error classes, per-endpoint enforcement, ≥30 test vectors | `claude_worklog/v2_architecture_remediation/12B_API_LINEAGE_ENFORCEMENT_CLOSURE.md` | CLOSED at architecture-text level |
| 3 | Feature snapshot completeness and confidence explainability cardinality | `claude_worklog/v2_architecture/11_FEATURE_ATTRIBUTION_AND_SIGNAL_EXPLAINABILITY_ARCHITECTURE.md` §3, §3.3, §3.4, §4, §6, §7.3, §7.4, §7.5 — canonical `feature_snapshot` shape, source-grounding tuple, `feature_set_manifest`, completeness-valid predicate, eleven `feature_snapshot.*` and nine `confidence.*` rejection classes, ≥3 cardinality on top contributor lists with explicit placeholders | `claude_worklog/v2_architecture_remediation/12C_FEATURE_EXPLAINABILITY_CLOSURE.md` | CLOSED at architecture-text level |
| 4 | Trainer liveness validation evidence on the corrected monitor | `claude_worklog/v2_architecture/14_CONTINUOUS_MONITORING_AND_EVIDENCE_PACKET_ARCHITECTURE.md` §2.1–§2.5, §3, §5, §7 — five-dimension contract, local-tz log assumption, stream-ID growth over `XLEN`, composite `liveness_confidence_level`, six-packet model, twenty-plus envelope fields, six packet rejection classes, dashboard gate metrics. Reference run `2026-04-30T21:39:44Z` → `2026-04-30T21:49:44Z`, 9 snapshots, false-CRITICAL count `0`. | `claude_worklog/v2_architecture_remediation/12D_TRAINER_LIVENESS_EVIDENCE_CLOSURE.md` | CLOSED at architecture-text level |
| 5 | Codex adversarial rerun on the post-remediation architecture set | `claude_worklog/v2_architecture_codex_review/15_ACTUAL_CODEX_RERUN_AFTER_REMEDIATION.md` updated to incorporate 12A–12D, and `16_ACTUAL_CODEX_RERUN_GO_NO_GO.md` flipped to `ACTUAL_CODEX_ARCHITECTURE_RERUN_PASS` | n/a (Codex artefact) | OPEN — current value is `ACTUAL_CODEX_ARCHITECTURE_RERUN_FAIL`; Codex rerun task `010_actual_codex_architecture_rerun_after_remediation` MUST run on items 1–4 before this gate flips |

Items 1–4 are the prerequisite reading for the Codex rerun in item 5. Until item 5 flips to PASS, scaffold planning (milestone B) is BLOCKED. The architecture-tier closure of items 1–4 is not by itself sufficient to scaffold; only Codex rerun PASS authorizes milestone B.

## 4. Sequence

The sequence is strictly ordered. A milestone may not begin until the prior milestone is marked complete by the supervisor and any cross-cutting gate evidence required by §3 or §5 is resolved.

A. Architecture review
B. V2 skeleton/scaffold
C. Database schema (materialization)
D. API contracts (materialization)
E. Enterprise GUI shell
F. Monitor / evidence packet viewer
G. Passive market discovery
H. Adaptive selection engine
I. Feature attribution store
J. Trainer adapter (read-only)
K. Risk gateway
L. Replay / paper
M. Trader fleet (paper-only)
N. Live readiness gate
O. Live mode (only after explicit approval)

## 5. Per-milestone gate matrix

For each milestone the matrix names: the required entry evidence (gate IN), the validation artifact produced inside the milestone (gate OUT), the governance level required to authorize the transition, and the immediate downstream blocker.

### A. Architecture review

- Gate IN: requirements set under `claude_worklog/v2_requirements/`, post-monitor findings under `claude_worklog/post_monitor/`, prior Codex review artefacts under `claude_worklog/v2_architecture_codex_review/`.
- Gate OUT: every architecture file under `claude_worklog/v2_architecture/` plus the four remediation closures `12A`–`12D`. Status of A is governed by `claude_worklog/v2_architecture/18_ARCHITECTURE_REVIEW_GO_NO_GO.md`.
- Governance: L1 (architecture-only artefacts).
- Downstream blocker: §3 items 1–4 must be CLOSED and §3 item 5 must be PASS before B may begin.
- Current status: A is COMPLETE at architecture-text level for items 1–4; A is NOT yet build-ready because §3 item 5 is OPEN. `18_ARCHITECTURE_REVIEW_GO_NO_GO.md` is set to `ARCHITECTURE_READY_FOR_CODEX_RERUN` (not `BUILD_READY`).

### B. V2 skeleton/scaffold

- Gate IN: §3 items 1–5 all resolved (closure files present + Codex rerun PASS). Supervisor verifies each `gate_evidence_ref`.
- Gate OUT: V2 repository skeleton under `v2/` with module boundaries matching the architecture (control plane, FastAPI app, GUI shell, monitor adapters, trainer adapter stub, risk gateway stub, replay/paper stub). Validation artifact: `claude_worklog/v2_build/B_SCAFFOLD_VALIDATION.md` enumerating modules created, lint/type-check passing, and import graph with no cycles.
- Governance: L2 (introduces files but no runtime behavior).
- Downstream blocker: scaffold validation artifact must be present before C.
- Current status: BLOCKED. Will remain blocked until §3 item 5 flips.

### C. Database schema (materialization)

- Gate IN: B complete; `03_DATABASE_SCHEMA.md` reviewed and frozen for the milestone; `12A` closure verified.
- Gate OUT: Alembic (or equivalent) migrations creating every table, column, NOT NULL, FK with `ON DELETE/UPDATE RESTRICT`, CHECK, and index listed in `03_DATABASE_SCHEMA.md`. Validation artifact: `claude_worklog/v2_build/C_DATABASE_VALIDATION.md` with `psql \d+` outputs proving each constraint exists, plus a constraint-coverage matrix mapping every architecture-level NOT NULL/FK/CHECK to a materialized DDL line.
- Governance: L2.
- Downstream blocker: any missing constraint reopens `12A`.

### D. API contracts (materialization)

- Gate IN: C complete; `05_API_CONTRACTS.md` reviewed and frozen; `12B` closure verified.
- Gate OUT: FastAPI route surface implementing the canonical lineage block (§1.3.1), the nine pre-handler validators (§9.1), the seven `lineage.*` error classes (§3.2/§3.3), the §3.4 DB-integrity-error translator, and the §13 test vectors as fixtures. Validation artifact: `claude_worklog/v2_build/D_API_VALIDATION.md` with the test-vector pass matrix (one row per vector, expected status + expected class + actual status + actual class).
- Governance: L2.
- Downstream blocker: any vector failure reopens `12B`.

### E. Enterprise GUI shell

- Gate IN: D complete; navigation tree mapped to the 26 GUI pages enumerated in `CLAUDE.md` (`Required V2 GUI Pages`).
- Gate OUT: routable shell with placeholder pages for all 26, RBAC-aware navigation, default-deny on dangerous controls, default `LIVE TRADING: BLOCKED` banner. Validation artifact: `claude_worklog/v2_build/E_GUI_SHELL_VALIDATION.md` with screenshot evidence (or rendered HTML snapshots) and a checklist row per page.
- Governance: L2.

### F. Monitor / evidence packet viewer

- Gate IN: E complete; `12D` closure verified; reference validation run from `12D` §3.2 still within `validation_max_age_hours`. If stale, a re-validation run MUST be produced before F begins.
- Gate OUT: Monitor Center, Trainer Prediction Monitor, Live Readiness, and Build/Validation Status pages reading `evidence_packets` and `validation_runs` tables, surfacing `liveness_confidence_level`, `dimension_status`, `streams[]`, `validation_evidence_ref`, and `packet_rejection_rate_15m`. Validation artifact: `claude_worklog/v2_build/F_MONITOR_VALIDATION.md` with rendered packet samples per packet type and a rejection-class rendering matrix.
- Governance: L2.

### G. Passive market discovery

- Gate IN: F complete.
- Gate OUT: read-only market scanner emitting candidate symbols to a V2-namespaced surface, no order placement, no leverage change, no margin change. Validation artifact: `claude_worklog/v2_build/G_DISCOVERY_VALIDATION.md` with raw output samples.
- Governance: L2.

### H. Adaptive selection engine

- Gate IN: G complete.
- Gate OUT: selection engine consuming discovery output and emitting a ranked candidate set; deterministic, replayable. Validation artifact: `claude_worklog/v2_build/H_SELECTION_VALIDATION.md` with deterministic seed evidence.
- Governance: L2.

### I. Feature attribution store

- Gate IN: H complete; `12C` closure verified.
- Gate OUT: `feature_snapshots` table populated by the V2 feature-assembly stage with deterministic `feature_snapshot_id`, full `feature_sources[]` source-grounding tuples, `feature_set_manifest` lookup, the §4 completeness-valid validator, and the eleven `feature_snapshot.*` rejection classes wired to the API. Validation artifact: `claude_worklog/v2_build/I_FEATURE_STORE_VALIDATION.md` with snapshot samples + rejection-class coverage matrix.
- Governance: L2.

### J. Trainer adapter (read-only)

- Gate IN: I complete; `LEGACY_TRAINER_PYTHON`, `LEGACY_BOT_ROOT`, and `V2_REDIS_PREFIX` environment variables recorded; subprocess boundary enforced per `CLAUDE.md` Protected Runtime Policy.
- Gate OUT: subprocess-boundary adapter that calls existing trainer scripts in read-only/status/export mode, records every call to the audit ledger, and never imports trainer modules into the FastAPI process unless dependency safety is independently proven. Validation artifact: `claude_worklog/v2_build/J_TRAINER_ADAPTER_VALIDATION.md` with raw subprocess invocation transcripts and audit-ledger entries.
- Governance: L3 (touches the protected runtime even if read-only).

### K. Risk gateway

- Gate IN: J complete; `12_RISK_GATEWAY_ARCHITECTURE.md` reviewed; `13_AUDIT_LEDGER_AND_AI_CHANGE_GOVERNANCE.md` L0–L5 taxonomy materialized.
- Gate OUT: risk gateway implementing non-bypass invariants, deterministic phase order, failure precedence, duplicate guard, stale defaults, policy bundle states, kill-switch persistence, live-readiness state, and connector-side hard blocks. Validation artifact: `claude_worklog/v2_build/K_RISK_VALIDATION.md` with the architecture's test vectors as fixtures + pass matrix.
- Governance: L3.

### L. Replay / paper

- Gate IN: K complete.
- Gate OUT: deterministic replay over historical data and paper-mode loop emitting `execution_intents.mode='paper'`. Validation artifact: `claude_worklog/v2_build/L_REPLAY_PAPER_VALIDATION.md` with chain-walk transcripts proving every paper trade resolves back to its `feature_snapshot_id` and `confidence_explainability` block.
- Governance: L3.

### M. Trader fleet (paper-only)

- Gate IN: L complete.
- Gate OUT: multi-trader fleet running in paper-only mode against the risk gateway and replay/paper surfaces. Validation artifact: `claude_worklog/v2_build/M_PAPER_FLEET_VALIDATION.md` with per-trader behavior trace.
- Governance: L3.

### N. Live readiness gate

- Gate IN: M complete; Live Readiness page (from F) shows GO inputs all green: `liveness_confidence_level >= medium` AND `validation_run_age_hours <= validation_max_age_hours` AND `validation_run_false_critical_count == 0` AND `packet_rejection_rate_15m == 0` (per `14_CONTINUOUS_MONITORING_AND_EVIDENCE_PACKET_ARCHITECTURE.md` §7).
- Gate OUT: live readiness checklist artifact `claude_worklog/v2_build/N_LIVE_READINESS_VALIDATION.md` with raw evidence pointers for every checklist row. This artifact does NOT enable live trading; it merely makes a request to L4/L5 governance.
- Governance: L3 to produce; L4 to consume.

### O. Live mode (only after explicit approval)

- Gate IN: N complete; explicit human L5 approval recorded in the audit ledger per `13_AUDIT_LEDGER_AND_AI_CHANGE_GOVERNANCE.md` (subject/body bound, single-use consumption); explicit human L4 approval for each dangerous setting per `CLAUDE.md` (`Admin Control Rule`).
- Gate OUT: live mode enabled for a strictly-bounded surface (single account, single exchange, capped notional, capped leverage, kill switch armed). Validation artifact: `claude_worklog/v2_build/O_LIVE_ACTIVATION_VALIDATION.md` with the L5 approval-chain hash and the live-mode envelope.
- Governance: L5 (human only).
- Default: BLOCKED. Live mode remains blocked until O is explicitly authorized. Reaching milestones A–N does not automatically authorize O.

## 6. Validation artifact catalog

Every milestone produces exactly one validation artifact path under `claude_worklog/v2_build/`. Each artifact MUST contain:

1. The milestone label (A–O).
2. The `gate_evidence_ref` actually consumed (closure files, Codex rerun result, prior milestone artefact).
3. The acceptance checklist for the milestone, with one row per requirement and a raw-evidence pointer per row (file path + line range, raw command output, or DB row identifier).
4. The `produced_by` agent identity and the `verified_by[]` reviewers (Claude, Codex, human).
5. The `confidence` level and any `missing_evidence[]` items. A milestone with non-empty `missing_evidence[]` is NOT complete.

Validation artifacts are append-only; corrections are recorded as new artifacts referencing the prior artifact's hash.

## 7. Cross-cutting governance gates

The L0–L5 governance taxonomy from `13_AUDIT_LEDGER_AND_AI_CHANGE_GOVERNANCE.md` applies to every milestone transition:

- L0/L1: read-only inspection, architecture-text edits — supervisor or Claude can authorize.
- L2: V2 code that does not touch the protected runtime, does not write the legacy Redis, does not place orders — supervisor + reviewer (Claude or Codex) authorize.
- L3: V2 code that calls the protected runtime (read-only), or implements the risk gateway, or runs paper-mode trades — supervisor + reviewer + human acknowledge.
- L4: dangerous-setting changes (live API key add/activate, leverage increase, CROSS margin, max position size increase, daily loss limit increase, kill switch disable, mandatory stop disable, hedge/DCA enable, ADJUST_LEVERAGE enable, paper→live switch) — explicit human approval, single-use consumption, audit-ledger entry.
- L5: live-mode activation — explicit human approval, two-person rule recommended, kill switch armed, audit-ledger entry with subject/body binding.

A milestone never elevates its own governance level. A milestone whose validation artifact relies on an L4 or L5 approval MUST cite the approval's audit-ledger entry hash.

## 8. Live readiness preconditions (summary)

Live trading remains BLOCKED until ALL of the following are simultaneously true:

1. Milestones A–N complete with passing validation artifacts.
2. `liveness_confidence_level=high` on the Trainer Prediction Monitor at the time of activation, with the §3.2 reference run still fresh.
3. Risk gateway in `policy_bundle_state=active` with kill switch armed.
4. `LIVE TRADING: BLOCKED` banner explicitly toggled off by L5 approval, with the toggle recorded in the audit ledger.
5. Per-account dangerous settings each carrying their own L4 approvals.
6. Codex review of the live-activation envelope passes.
7. Human acknowledgement that the activation is bounded (single account, single exchange, capped notional, capped leverage).

Failing any one of the above blocks O. The default is BLOCKED.

## 9. Status

Sequence and milestone gating: DEFINED. Pre-scaffold gate evidence: §3 items 1–4 CLOSED at architecture-text level; §3 item 5 (Codex rerun) OPEN. Milestone A: ready for Codex rerun, NOT build-ready. Milestones B–O: BLOCKED pending §3 item 5 PASS and prior-milestone completion.

A future supervisor task `010_actual_codex_architecture_rerun_after_remediation` will run the Codex adversarial rerun against items 1–4. Only when its output flips `claude_worklog/v2_architecture_codex_review/16_ACTUAL_CODEX_RERUN_GO_NO_GO.md` to `ACTUAL_CODEX_ARCHITECTURE_RERUN_PASS` does milestone B become eligible to begin, and even then only under L2 governance with the §3 evidence pack attached.

Any deviation from §3 (gate evidence) or §5 (per-milestone matrix) reopens this document.