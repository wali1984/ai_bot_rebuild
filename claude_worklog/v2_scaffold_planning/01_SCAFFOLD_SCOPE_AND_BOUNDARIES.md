# 01 — V2 Scaffold Scope and Boundaries

## 1. Purpose
This package is the milestone-B planning artifact required by `claude_worklog/v2_architecture/17_IMPLEMENTATION_SEQUENCE_AND_MILESTONES.md` §5.B. It defines the boundaries inside which V2 scaffold code may eventually be written. It does not author runtime code, deployable apps, services, jobs, or migrations; those are produced inside milestones B–O under their own validation artifacts. This document is L1 (architecture-tier planning text).

## 2. Gate evidence consumed
Per §3 of the milestone document, scaffold planning is only eligible after all five pre-scaffold gates resolve. The status read at planning time is:

| # | Gate item | Reference | Status |
|---|-----------|-----------|--------|
| 1 | Database lineage chain enforceable end-to-end | `claude_worklog/v2_architecture/03_DATABASE_SCHEMA.md` + `claude_worklog/v2_architecture_remediation/12A_DATABASE_LINEAGE_CLOSURE.md` | CLOSED at architecture-text level |
| 2 | API lineage carriage and rejection classes | `claude_worklog/v2_architecture/05_API_CONTRACTS.md` + `12B_API_LINEAGE_ENFORCEMENT_CLOSURE.md` | CLOSED at architecture-text level |
| 3 | Feature snapshot completeness and confidence explainability | `claude_worklog/v2_architecture/11_FEATURE_ATTRIBUTION_AND_SIGNAL_EXPLAINABILITY_ARCHITECTURE.md` + `12C_FEATURE_EXPLAINABILITY_CLOSURE.md` | CLOSED at architecture-text level |
| 4 | Trainer liveness validation evidence | `claude_worklog/v2_architecture/14_CONTINUOUS_MONITORING_AND_EVIDENCE_PACKET_ARCHITECTURE.md` + `12D_TRAINER_LIVENESS_EVIDENCE_CLOSURE.md` | CLOSED at architecture-text level |
| 5 | Codex adversarial rerun on the post-remediation set | `claude_worklog/v2_architecture_codex_review/15_ACTUAL_CODEX_RERUN_AFTER_REMEDIATION.md` and `16_ACTUAL_CODEX_RERUN_GO_NO_GO.md` | PASS (`ACTUAL_CODEX_ARCHITECTURE_RERUN_PASS`) |

All five gates resolve. Scaffold planning is therefore eligible to proceed under L1 governance. Scaffold *materialization* (milestone B code creation) remains under L2 governance and is not authorized by this document.

## 3. Hard constraints (override every plan in this package)
The constraints below are quoted from `CLAUDE.md` and `17_IMPLEMENTATION_SEQUENCE_AND_MILESTONES.md` §2 and apply to every planning artifact 02–07:

- No live execution. Live trading remains BLOCKED. Scaffold code may never enable live mode; live mode is gated by milestones N and O and L4/L5 approvals.
- No mutation of the legacy bot at `/home/wali/Desktop/AI BOT`. Read-only inspection only.
- No writes to the legacy Redis namespace. V2 writes only to `${V2_REDIS_PREFIX}*` (default `v2:*`). Legacy keys are read-only.
- No restart of legacy services (trainer, trader, orchestrator, Redis, VPN). Recovery is human-gated.
- No Dockerization of the trainer; no upgrades to trainer-side packages. The protected ML runtime is preserved.
- No direct import of legacy trainer modules into the FastAPI process. The trainer adapter is subprocess-bounded.
- No demo, sample, or placeholder pages in production architecture. Every GUI page must bind to a real API/data source, including the placeholder pages produced in milestone B (which are wired to live API stubs that return real-shape empty payloads, not mock fixtures).
- Default `LIVE TRADING: BLOCKED` banner persists across all GUI pages until L5 approval.
- No order placement, leverage change, margin change, or kill-switch toggle from any scaffold-tier code.

## 4. Scope of milestone B (this package's plan)
Milestone B produces a non-runtime scaffold under `v2/`. The scaffold's deliverables are:

1. Repository skeleton with module boundaries matching the architecture (control plane, FastAPI app, GUI shell, monitor adapters, trainer adapter stub, risk gateway stub, replay/paper stub).
2. Build/lint/type-check tooling configured at the repo root (Python: `ruff`, `mypy`, `pytest`; TypeScript: `tsc`, `eslint`, `prettier`, `vitest` or `jest`).
3. CI configuration that runs the import-graph cycle check, lint, type-check, schema validation, and contract test placeholders.
4. Validation artifact `claude_worklog/v2_build/B_SCAFFOLD_VALIDATION.md` enumerating modules created, lint/type-check passing, and import-graph evidence.

Milestone B does NOT produce: database migrations executed against a live DB, FastAPI handlers that touch real Redis/DB, GUI pages with real backend coupling beyond stubs, trainer subprocess invocations, or risk-gateway decisions. Each of those is a downstream milestone (C–K) with its own gate evidence and validation artifact.

## 5. Out of scope (explicit)
- Live trading enablement (milestone O only).
- Legacy bot mutation of any kind.
- Redis namespace rewrites.
- Trainer venv mutations or pip installs into the protected runtime.
- Performance tuning, cache layer optimization, or production deployment automation.
- Any change to `.env` files or secrets.
- Authoring new ML models, retraining, or checkpoint promotion.
- iPhone-native (Swift/RN) app build. Only PWA-readiness is in scope; the iPhone app is a future surface preserved by mobile-safe API contracts.

## 6. Read/write boundaries (scaffold-tier)
- Read: `legacy_reference/**`, `audits/**`, `requirements/**`, `replay_data/**`, `claude_worklog/**`, `raw_evidence/**`, `ollama/outputs/**`, `ollama/evidence_packets/**`.
- Write: `v2/**` (scaffold tree only after gate passes), `claude_worklog/**`, `requirements/**`, `.claude/**`, `tools/**`, `ollama/prompts/**`, `ollama/scripts/**`, `ollama/outputs/**`, `ollama/evidence_packets/**`, `raw_evidence/**`.
- Forbidden: `legacy_reference/**`, `../AI BOT/**`, any `.env`, any secrets file. The supervisor's pre-dispatch check refuses any scaffold task whose write path escapes the allowed roots.

## 7. Cross-cutting requirements covered by this scaffold plan
The scaffold plan in 02–07 must accommodate the following requirement clusters drawn from `claude_worklog/v2_requirements/` and the architecture set:

- Enterprise website control center (`v2_requirements/10_ENTERPRISE_WEBSITE_PRODUCT_REQUIREMENTS.md`, `16_ENTERPRISE_GUI_PAGE_MAP.md`, `21_UPDATED_ENTERPRISE_ARCHITECTURE_READINESS.md`).
- Admin/public page split (`v2_architecture/06_ENTERPRISE_GUI_UX_ARCHITECTURE.md`, `15_PUBLIC_HOSTING_SECURITY_AND_RBAC_ARCHITECTURE.md`).
- Dynamic all-market passive universe (`v2_requirements/11_DYNAMIC_SYMBOL_UNIVERSE_REQUIREMENTS.md`, `19_PASSIVE_MARKET_DISCOVERY_AND_ADAPTIVE_SELECTION.md`, `v2_architecture/07_PASSIVE_MARKET_DISCOVERY_AND_ADAPTIVE_SELECTION_ARCHITECTURE.md`).
- Adaptive symbol selection (same files as above).
- Hot reload (`v2_requirements/14_HOT_RELOAD_PIPELINE_REQUIREMENTS.md`, `v2_architecture/08_HOT_RELOAD_PIPELINE_ARCHITECTURE.md`).
- Multi-exchange futures connectors (`v2_requirements/12_MULTI_EXCHANGE_CONNECTOR_REQUIREMENTS.md`, `v2_architecture/09_MULTI_EXCHANGE_CONNECTOR_ARCHITECTURE.md`).
- Multi-trader fleet (`v2_requirements/13_MULTI_TRADER_FLEET_REQUIREMENTS.md`, `v2_architecture/10_MULTI_TRADER_FLEET_ARCHITECTURE.md`).
- Feature snapshot lineage and confidence explainability (`v2_requirements/02_FEATURE_SNAPSHOT_SCHEMA.md`, `03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md`, `04_CONFIDENCE_EXPLAINABILITY_SCHEMA.md`, `v2_architecture/11_FEATURE_ATTRIBUTION_AND_SIGNAL_EXPLAINABILITY_ARCHITECTURE.md`, `12C` closure).
- Risk gateway (`v2_architecture/12_RISK_GATEWAY_ARCHITECTURE.md`).
- Audit ledger and AI change governance (`v2_architecture/13_AUDIT_LEDGER_AND_AI_CHANGE_GOVERNANCE.md`).
- Claude/Codex/Ollama supervision (`v2_requirements/20_AI_SUPERVISION_AND_AUTONOMOUS_CHANGE_GOVERNANCE.md`, `v2_architecture/13_AUDIT_LEDGER_AND_AI_CHANGE_GOVERNANCE.md`).
- Public hosting / security / RBAC (`v2_requirements/15_PUBLIC_HOSTING_AND_SECURITY_REQUIREMENTS.md`, `v2_architecture/15_PUBLIC_HOSTING_SECURITY_AND_RBAC_ARCHITECTURE.md`).
- iPhone / PWA readiness (`v2_architecture/16_MOBILE_IPHONE_AND_PWA_READINESS.md`, `CLAUDE.md` Mobile/iPhone Future Rule).
- Tests and CI (this package §07).

## 8. Output of the planning package
This package produces eight planning files and no code. The eight files are the milestone-B planning input bundle and must be cited as `gate_evidence_ref` for any subsequent milestone-B scaffold task. Scaffold task supervisors MUST refuse to dispatch milestone-B scaffold work whose `gate_evidence_ref` does not include this package and the §3 closure files.

## 9. Status
SCOPE: DEFINED. BOUNDARIES: ENFORCED. SCAFFOLD MATERIALIZATION: NOT YET AUTHORIZED. Authorization for milestone-B scaffold materialization requires a separate L2 task whose `gate_evidence_ref` cites this planning package plus the §3 closure files plus `16_ACTUAL_CODEX_RERUN_GO_NO_GO.md = ACTUAL_CODEX_ARCHITECTURE_RERUN_PASS`.