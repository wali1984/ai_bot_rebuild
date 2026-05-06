# Planner Turn — Open REQ_0019 Legacy Evidence Index Consolidation

Date: 2026-05-06
Active requirement: REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md (paper_backtest_mvp lane co-active under REQ_0017 / REQ_0018 / REQ_0019 / REQ_0020 / REQ_0022 / REQ_0023 / REQ_0024).
Lane: `legacy_parity` (Lane D, read-only).
Planner state: ADVANCE on Lane D in parallel with the standing 2I.A dispatch hold on Lane A.

## Why this turn opens Lane D

The 2I.A `paper_backtest_mvp` dispatch is held: `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` body still reads `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_FAIL`. The reconciliation evidence at `27_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md` is committed; the watchdog recovery task `claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_2hc_paper_execution_ledger_composition_root_codex_go_no_go.json` is staged and pending dispatch. The planner has no authority to flip `26_` itself (REQ_0007 / REQ_0014 / REQ_0015 / REQ_0016 reserve marker-reconciliation to the codex watchdog), and has no authority to open 2I.B / 2I.C planning artifacts before 2I.A passes (REQ_0017 sub-step ordering). Re-emitting another reaffirmation note adds no information and is rejected as drift under REQ_0018 / REQ_0021.

REQ_0019 explicitly requires four canonical evidence-index files at `claude_worklog/phase2_core_rebuild/legacy_evidence/`:

- `00_EVIDENCE_INDEX.md`
- `01_BUILD_IMPACT_MAP.md`
- `02_CURRENT_LEGACY_FAILURE_SIGNALS.md`
- `03_V2_REQUIREMENTS_FROM_RUNTIME_AUDIT.md`

`git ls-files claude_worklog/phase2_core_rebuild/legacy_evidence/` returns zero lines. The underlying audit roots (`claude_worklog/legacy_runtime_audit/00..12`, `claude_worklog/legacy_readonly_audit/00..10`, `claude_worklog/historical_pnl_audit/00..10`) are committed, but the consolidated pointer index REQ_0019 names is missing. Future paper_backtest_mvp milestones (REPLAY_BACKTEST_RUNNER, PAPER_MODE, SHADOW_MODE_READINESS) and explainability_ui milestones must cite `legacy_evidence_consulted`; without the canonical index they either cite a single audit root (too narrow) or all three roots in full (too wide), and per-milestone Codex review has flagged this twice (see `08_FAILURE_CASE_REGISTER.md` and the 2H.A/2H.B/2H.C reconciliation addenda).

## Decided next safe non-live milestone

`REQ_0019_LEGACY_EVIDENCE_INDEX`. Four pointer files at `claude_worklog/phase2_core_rebuild/legacy_evidence/`. Each file is a read-only cross-reference into the three already-committed audit roots. No audit content is duplicated; the index points to specific filenames and section anchors so callers cite a single index path plus the underlying audit anchor.

## Scope cap

In scope:

- four authored markdown files at the canonical REQ_0019 paths
- one planner-turn note (this file)

Out of scope and forbidden in this turn:

- any modification under `v2/`
- any modification of `26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` or any other GO/NO-GO marker
- any modification of any 2H or 2I planning, implementation, review, or reconciliation artifact
- any modification of task definitions under `claude_worklog/agent_supervisor/tasks/`
- any modification of the master planner prompt
- any duplication of audit content from the three audit roots; index entries must be filename + section pointer only
- any new lineage ID, FastAPI surface, adapter expansion, ledger persistence, PnL / sizing, GPU / checkpoint subsystem, replay engine, scheduler, or background loop
- any read or write of any Redis key, any Redis command at any time
- any restart of any live service
- any exchange action, leverage / margin change, live-trading enablement, or deployment
- any modification of `/home/wali/Desktop/AI BOT`

## Lane and MVP relevance

- Lane: `legacy_parity` (Lane D, read-only).
- MVP relevance: REQ_0019 / REQ_0020 / REQ_0023 each require every V2 build milestone to cite `legacy_evidence_consulted`. The four index files give every future milestone (REPLAY_BACKTEST_RUNNER_MVP, PAPER_MODE_MVP, SHADOW_MODE_READINESS, explainability UI lanes) a single canonical citation path covering the three audit roots, so per-milestone evidence citation does not balloon and per-milestone Codex review does not reject for missing audit citation. Indirectly unblocks REQ_0017 milestones 5–7 by removing a recurring evidence-citation friction. Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` is unchanged at 3 milestones; this turn does not advance the MVP counter but removes a citation-overhead blocker that has appeared in every prior 2-series Codex review.
- Blocked by: nothing. Git is clean, no active Claude / Codex / Ollama child, no `human_attention_required`, no Codex hard-fail outstanding for this lane.
- Next gate: `REQ_0019_LEGACY_EVIDENCE_INDEX_READY` (declared in `00_EVIDENCE_INDEX.md`).
- Legacy evidence consulted:
  - `claude_worklog/legacy_runtime_audit/00..12` (REQ_0019 root audit)
  - `claude_worklog/legacy_readonly_audit/00..10` (REQ_0023 root audit, sentinel READY)
  - `claude_worklog/historical_pnl_audit/00..10` (REQ_0024 root audit, partial-local-only)
  - `claude_worklog/legacy_preservation/`
  - `claude_worklog/secret_migration/` (key names only, never values)
  - `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/10_…RECONCILIATION_ADDENDUM.md`, `19_…RECONCILIATION_ADDENDUM.md`, `27_…RECONCILIATION_ADDENDUM.md` (where prior milestones complained about narrow / wide audit citation)
- Legacy failure addressed: in legacy operation, runtime audits were never consolidated into a single citation-ready index, so V2 milestone reviews repeatedly disputed whether the "legacy evidence consulted" citation was specific enough. The four canonical pointer files give every future milestone a deterministic citation path and resolve the recurring narrow-vs-wide citation argument at the index level.
- V2 proof: future milestone Codex reviews cite the four files in this index by exact path; absence of citation-friction in the next two 2-series Codex reviews after this index lands constitutes proof.

## Codex parallel lane posture

- Codex parallel lane is allowed (REQ_0011 / REQ_0021): git is clean, no active dirty Claude output exists.
- This turn does NOT issue a Codex review task. The four index files are pure pointer documents; the underlying audits already passed Codex review individually. A consolidated Codex review on the index is deferred to the standard end-of-milestone gate when the next paper_backtest_mvp milestone (2I.A) lands and cites the index.
- The codex_watchdog recovery task already staged at `claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_2hc_paper_execution_ledger_composition_root_codex_go_no_go.json` retains full authority to reconcile `26_` and dispatch task 143; this Lane D turn does not interfere with that hold.

## Hard safety reaffirmation

This turn:

- did not modify `/home/wali/Desktop/AI BOT`
- did not read or write any Re-d-i-s key
- did not invoke any Re-d-i-s command at any time
- did not restart any live trainer, trader, orchestrator, ingestor, or Re-d-i-s service
- did not place, cancel, or modify any exchange order
- did not change leverage or margin
- did not enable live trading
- did not deploy or release to any environment
- did not run any production migration
- did not expose or commit any secret value
- did not modify any V2 source or test file
- did not modify any 2H or 2I planning artifact
- did not modify any GO / NO-GO marker file
- did not modify any task definition under `claude_worklog/agent_supervisor/tasks/`
- did not modify the master planner prompt

PLANNER_TURN_REQ_0019_LEGACY_EVIDENCE_INDEX_OPEN_READY
