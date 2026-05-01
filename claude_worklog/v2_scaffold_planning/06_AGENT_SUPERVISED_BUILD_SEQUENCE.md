# 06 — Agent-Supervised Build Sequence

## 1. Purpose
Define the supervised order in which V2 modules are built, starting at milestone B and continuing through milestone N. Live-mode O remains separate and human-only. Each milestone's gate evidence, validation artifact, and required reviewer set are restated from `claude_worklog/v2_architecture/17_IMPLEMENTATION_SEQUENCE_AND_MILESTONES.md` §4–§5 and bound to the supervisor's pre-dispatch check.

## 2. Supervisor / agent roster
- Supervisor — `claude_worklog/agent_supervisor/` queue manager. Refuses to dispatch a task whose `gate_evidence_ref` does not resolve.
- Claude (this agent) — primary builder for L1/L2 work; reviewer at gates.
- Codex — adversarial reviewer at A→B, C→D, K→L, N→O. Codex never authors V2 code.
- Ollama — low-risk summarization, draft inventories, anomaly grouping. Ollama never makes final safety claims and never approves a milestone.
- Human — required at L3 acknowledgement, L4 approvals, and L5 activation.

## 3. Build order (planning-only; matches §4 of 17_IMPLEMENTATION_SEQUENCE)
A. Architecture review — COMPLETE (gate IN met; gate OUT artifacts present including `15_ACTUAL_CODEX_RERUN_AFTER_REMEDIATION.md` PASS and `16_ACTUAL_CODEX_RERUN_GO_NO_GO.md = ACTUAL_CODEX_ARCHITECTURE_RERUN_PASS`).
B. V2 skeleton/scaffold — eligible to begin once this planning package is consumed as `gate_evidence_ref`.
C. Database schema (materialization).
D. API contracts (materialization).
E. Enterprise GUI shell.
F. Monitor / evidence packet viewer.
G. Passive market discovery.
H. Adaptive selection engine.
I. Feature attribution store.
J. Trainer adapter (read-only).
K. Risk gateway.
L. Replay / paper.
M. Trader fleet (paper-only).
N. Live readiness gate.
O. Live mode (only after explicit approval) — out of this plan; L5 human-only.

## 4. Per-milestone supervisor checks
For every milestone B–N the supervisor enforces:

1. `gate_evidence_ref` resolves to all required closure files plus the prior milestone's validation artifact.
2. The task's `write_paths` lie under `v2/**` or `claude_worklog/**` (forbidden roots: `legacy_reference/**`, `../AI BOT/**`, any `.env`).
3. The task's `governance_level` matches the milestone's required level (L2/L3/L4 per §7 of 17_IMPLEMENTATION_SEQUENCE).
4. The task declares the validation artifact path under `claude_worklog/v2_build/<letter>_*_VALIDATION.md` and a `produced_by` agent identity.
5. After completion, the supervisor verifies the validation artifact exists, contains a non-empty acceptance checklist with raw evidence pointers per row, names `verified_by[]`, and has `missing_evidence: []`.

A milestone with non-empty `missing_evidence[]` is not complete; the supervisor refuses to dispatch the next milestone.

## 5. Reviewer assignments per milestone
| Milestone | Authoring | Reviewer (Claude/Codex) | Human ack |
|-----------|-----------|--------------------------|-----------|
| B | Claude | Claude self-review + Codex adversarial pass on import graph + module boundaries | none (L2) |
| C | Claude | Claude + Codex on lineage constraint coverage matrix | none (L2) |
| D | Claude | Codex on test-vector pass matrix; Claude on middleware order | none (L2) |
| E | Claude | Claude self-review on RBAC + banner; Codex on default-deny inventory | none (L2) |
| F | Claude | Codex on packet rejection rendering + run-age windowing | none (L2) |
| G | Claude | Claude + Codex on read-only invariants | none (L2) |
| H | Claude | Claude on determinism + replay seed evidence | none (L2) |
| I | Claude | Codex on completeness predicate + cardinality placeholder rule | none (L2) |
| J | Claude | Claude on subprocess boundary + audit emission | human ack (L3) — protected runtime |
| K | Claude | Codex on non-bypass invariants + phase order + kill switch | human ack (L3) |
| L | Claude | Claude on chain-walk transcripts | human ack (L3) |
| M | Claude | Claude on per-trader trace + paper-only invariant | human ack (L3) |
| N | Claude | Codex on GO-input checklist + freshness window | L3 produce, L4 consume |
| O | n/a (out of plan) | Codex on activation envelope | L4 + L5 (human-only) |

## 6. Validation artifact catalog (planning view)
- `claude_worklog/v2_build/B_SCAFFOLD_VALIDATION.md` — modules created, lint/type-check passing, import graph evidence (no cycles).
- `claude_worklog/v2_build/C_DATABASE_VALIDATION.md` — `psql \d+` outputs, constraint-coverage matrix.
- `claude_worklog/v2_build/D_API_VALIDATION.md` — test-vector pass matrix.
- `claude_worklog/v2_build/E_GUI_SHELL_VALIDATION.md` — page-by-page checklist + screenshot/HTML evidence.
- `claude_worklog/v2_build/F_MONITOR_VALIDATION.md` — packet samples per packet type + rejection-class rendering matrix.
- `claude_worklog/v2_build/G_DISCOVERY_VALIDATION.md` — raw scanner output samples.
- `claude_worklog/v2_build/H_SELECTION_VALIDATION.md` — deterministic seed evidence.
- `claude_worklog/v2_build/I_FEATURE_STORE_VALIDATION.md` — snapshot samples + rejection-class coverage.
- `claude_worklog/v2_build/J_TRAINER_ADAPTER_VALIDATION.md` — subprocess invocation transcripts + audit-ledger entries.
- `claude_worklog/v2_build/K_RISK_VALIDATION.md` — risk gateway test-vector pass matrix.
- `claude_worklog/v2_build/L_REPLAY_PAPER_VALIDATION.md` — chain-walk transcripts.
- `claude_worklog/v2_build/M_PAPER_FLEET_VALIDATION.md` — per-trader behavior trace.
- `claude_worklog/v2_build/N_LIVE_READINESS_VALIDATION.md` — GO-input checklist with raw evidence pointers.
- `claude_worklog/v2_build/O_LIVE_ACTIVATION_VALIDATION.md` — L5 approval-chain hash + live-mode envelope (out of this plan).

## 7. Cross-cutting governance
The L0–L5 governance taxonomy from `13_AUDIT_LEDGER_AND_AI_CHANGE_GOVERNANCE.md` applies to every transition. A milestone never elevates its own level; humans gate L4/L5 explicitly with single-use approval consumption and subject/body binding.

## 8. Failure recovery
- Any milestone whose validation artifact is incomplete reopens the upstream closure file (e.g., a failing API vector reopens `12B`).
- A failing Codex review at any gate reopens the milestone for remediation; the supervisor records the rerun result in a new validation artifact rather than mutating the prior one.
- Audit-chain breaks (audit `chain_break` event) freeze the entire pipeline; no further milestones dispatch until human reviews the break.

## 9. Hard guards repeated
- No live trading at any milestone B–N.
- No legacy bot mutation.
- No legacy Redis writes.
- No restart of legacy services.
- No trainer venv mutation.
- No `.env` writes.

## 10. Status
BUILD SEQUENCE: PLANNED. SUPERVISOR CHECKS: ENUMERATED. AUTHORIZATION TO DISPATCH MILESTONE B IS A SEPARATE L2 TASK.