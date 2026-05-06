# Planner Turn — REQ_0019 Legacy Evidence Index Awaiting Watchdog Commit

Date: 2026-05-06
Active requirement: REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md (paper_backtest_mvp lane co-active under REQ_0017 / REQ_0018 / REQ_0019 / REQ_0020 / REQ_0022 / REQ_0023 / REQ_0024).
Active MVP target: `V2_BACKTEST_AND_PAPER_MVP_READY` (4 milestones remaining: PAPER_EXECUTION_LEDGER_MVP, REPLAY_BACKTEST_RUNNER_MVP, PAPER_MODE_MVP, SHADOW_MODE_READINESS).
Active MVP milestone: PAPER_EXECUTION_LEDGER_MVP (sub-step 2H-C composition root marker reconciliation pending) → REPLAY_BACKTEST_RUNNER_MVP (sub-step 2I.A domain implementation queued behind reconciliation).
Lane: `legacy_parity` (Lane D, read-only) hold note + Lane A status callout.
Planner state: HOLD — no new artifacts emitted this turn.

## Why this turn emits no new work

This turn is the first follow-up to `PLANNER_TURN_REQ_0019_LEGACY_EVIDENCE_INDEX_OPEN.md`. That prior turn opened Lane D and authored, inside the canonical REQ_0019 directory `claude_worklog/phase2_core_rebuild/legacy_evidence/`, the four pointer files REQ_0019 names plus the open-turn note. `git status --short` at the start of this turn returns exactly one entry — `?? claude_worklog/phase2_core_rebuild/legacy_evidence/` — confirming all five files are staged on disk and uncommitted. Re-emitting any of them would duplicate authored content under REQ_0018 drift guard. Re-emitting another open-turn note would duplicate intent under REQ_0021 capacity guidance.

Concurrently on Lane A (`paper_backtest_mvp`), the dispatch of task `143_replay_backtest_runner_2ia_domain_implementation` is held by the predecessor-marker contract: the body of `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` still reads `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_FAIL` while the reconciliation evidence at `27_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md` is committed and the recovery task `claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_2hc_paper_execution_ledger_composition_root_codex_go_no_go.json` is staged. Per REQ_0007 / REQ_0014 / REQ_0015 / REQ_0016, marker reconciliation is reserved to the Codex watchdog; the planner has no authority to flip `26_` itself, and the planner cannot author 2I.B / 2I.C planning artifacts before 2I.A passes (REQ_0017 sub-step ordering).

The correct planner action this turn is therefore:

- emit only this single hold note in the lane-D directory
- do not re-author the four REQ_0019 pointer files
- do not re-author the prior REQ_0019 open-turn note
- do not re-author or reaffirm any 2H-C / 2I.A artifact
- do not regenerate task definitions 143 or 144
- do not advance to 2I.B / 2I.C / sibling lanes until the dispatch precondition is satisfied
- do not open Lane B explainability_ui until the lineage IDs from MVP backbone are committed under V2 contracts
- do not open new Lane C codex_watchdog tasks; the watchdog already has both relevant items in queue

## Files awaiting Codex watchdog commit

Lane D — REQ_0019 evidence index (this directory):

- `claude_worklog/phase2_core_rebuild/legacy_evidence/00_EVIDENCE_INDEX.md`
- `claude_worklog/phase2_core_rebuild/legacy_evidence/01_BUILD_IMPACT_MAP.md`
- `claude_worklog/phase2_core_rebuild/legacy_evidence/02_CURRENT_LEGACY_FAILURE_SIGNALS.md`
- `claude_worklog/phase2_core_rebuild/legacy_evidence/03_V2_REQUIREMENTS_FROM_RUNTIME_AUDIT.md`
- `claude_worklog/phase2_core_rebuild/legacy_evidence/PLANNER_TURN_REQ_0019_LEGACY_EVIDENCE_INDEX_OPEN.md`

This turn adds:

- `claude_worklog/phase2_core_rebuild/legacy_evidence/PLANNER_TURN_REQ_0019_LEGACY_EVIDENCE_INDEX_AWAITING_WATCHDOG_COMMIT.md` (this file)

Lane A — already-staged watchdog recovery task for the 2H-C marker:

- `claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_2hc_paper_execution_ledger_composition_root_codex_go_no_go.json` (already committed; not in the dirty set; queued for watchdog dispatch)

All paths are inside `/home/wali/Desktop/AI BOT REBUILD` and inside approved planner write boundaries. None touch `/home/wali/Desktop/AI BOT`, Redis, live services, the exchange, leverage / margin, deployment, or secrets.

## Codex watchdog action requested

Per REQ_0007 / REQ_0011 / REQ_0014 / REQ_0015 / REQ_0016 / REQ_0021 the Codex watchdog is requested to perform two independent recoveries:

1. Lane D evidence-index commit:
   - inspect the dirty tree limited to `claude_worklog/phase2_core_rebuild/legacy_evidence/`
   - confirm no active Claude / Codex / Ollama child is generating these files (this turn emits only the hold note above)
   - run a high-confidence secret scan over the five staged paths
   - commit with a message such as `Codex watchdog recover REQ_0019 legacy evidence index pointer files (Lane D, read-only)`
   - push
2. Lane A 2H-C marker reconciliation dispatch:
   - dispatch the staged recovery task `codex_recover_fail_marker_2hc_paper_execution_ledger_composition_root_codex_go_no_go.json` against the now-clean repo
   - reconcile `26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` body to `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS` based on the already-committed `27_…RECONCILIATION_ADDENDUM.md`
   - commit / push
   - re-evaluate dispatch readiness for `143_replay_backtest_runner_2ia_domain_implementation`

Dispatch ordering: action 1 must complete before action 2 because action 2 itself requires a clean worktree. Action 2 must complete before task 143 may dispatch, because 143's `predecessor_required_marker_file` is the same `26_` file.

Once both recoveries land, task 143 (Lane A) and the queued 11 pending supervisor entries become eligible for normal dispatch under the parallel capacity scheduler (REQ_0021).

## What this turn does not change

- No `v2/` source or test file is read or written.
- No prior milestone artifact byte content is modified.
- No 2H-A, 2H-B, 2H-C, 2I.A planning / implementation / review / reconciliation file is modified.
- No task definition under `claude_worklog/agent_supervisor/tasks/` is modified.
- No master planner prompt is modified.
- No Redis key is read, written, or deleted.
- No live service is started, stopped, or restarted.
- No exchange action, leverage / margin change, live-trading enablement, or deployment is performed.
- No secret value is printed or committed; only env / config key names are referenced (none in this note).
- No content from `/home/wali/Desktop/AI BOT` is modified.

## Lane and MVP relevance

- Lane: `legacy_parity` (Lane D, read-only) for the hold note; status callout to Lane A `paper_backtest_mvp` for the 2H-C marker reconciliation hold.
- MVP relevance: this turn does not advance the MVP counter. The Lane D evidence index, once committed, gives every future MVP milestone a deterministic citation path for `legacy_evidence_consulted`, removing the citation-friction blocker that has appeared in 2H-A / 2H-B / 2H-C Codex reviews. The Lane A 2H-C marker reconciliation, once committed, unblocks 2I.A → 2I.B → 2I.C → REPLAY_BACKTEST_RUNNER_MVP and the remaining MVP path to `V2_BACKTEST_AND_PAPER_MVP_READY`.
- Blocked by: Codex watchdog commit of the five Lane D files, then watchdog dispatch of the 2H-C marker recovery task, then watchdog commit of the marker flip.
- Next gate: `REQ_0019_LEGACY_EVIDENCE_INDEX_READY` (declared in `00_EVIDENCE_INDEX.md`) and `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS` (Lane A predecessor marker for 143).
- Legacy evidence consulted: the three audit roots already enumerated in the prior open-turn note (`claude_worklog/legacy_runtime_audit/00..12`, `claude_worklog/legacy_readonly_audit/00..10`, `claude_worklog/historical_pnl_audit/00..10`). This turn adds no new evidence citation; it only re-points to the prior open-turn note for the full list.
- Legacy failure addressed: same dual blocker the prior open-turn note identified (citation-friction in Codex reviews + the residual 2H-C `FAIL` marker body). No new failure introduced or addressed by this hold turn.
- V2 proof: absence of citation-friction in the next two 2-series Codex reviews after the index lands, plus successful dispatch of `143_replay_backtest_runner_2ia_domain_implementation` after the marker flip.

## Escalation note on reaffirmation count

This is the first reaffirmation of the REQ_0019 index hold and the first lane-D-anchored callout of the 2H-C marker hold. If the Codex watchdog has not committed the Lane D files within the next two planner cycles, or has not dispatched the 2H-C marker recovery within the next two planner cycles, the planner will stop emitting numbered REQ_0019 reaffirmations and will instead emit a single watchdog-stall diagnostic note recommending human inspection of the watchdog child rather than continuing to grow this counter. Continuing to emit reaffirmations indefinitely would itself become drift under REQ_0018 / REQ_0021.

No further reaffirmation will be issued before this turn's note is committed alongside the prior five Lane D files.

## Hard safety reaffirmation

This turn:

- did not modify `/home/wali/Desktop/AI BOT`
- did not read or write any Redis key
- did not invoke any Redis command
- did not restart any live service
- did not place or cancel any exchange order
- did not change leverage or margin
- did not enable live trading
- did not deploy
- did not run any production migration
- did not expose or commit any secret
- did not bypass the final live approval gate

Final live trading remains blocked. Final live approval remains human-only. More automation capacity does not grant live authority.
