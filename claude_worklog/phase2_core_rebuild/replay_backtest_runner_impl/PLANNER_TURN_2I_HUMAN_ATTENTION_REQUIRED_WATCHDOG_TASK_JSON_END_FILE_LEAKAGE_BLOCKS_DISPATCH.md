# PLANNER TURN — Phase 2I.A — Human Attention Required: Watchdog Recovery Task JSON Has END_FILE Marker Leakage Blocking Supervisor Dispatch

## Active requirement

- `REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md` (intersect REQ_0014 / REQ_0015 / REQ_0016 / REQ_0017 / REQ_0018 / REQ_0020 / REQ_0021).

## Active lane

- `codex_watchdog` (Lane C). Downstream beneficiary lane is `paper_backtest_mvp` (Lane A) for REQ_0017 milestone 5 `REPLAY_BACKTEST_RUNNER_MVP`.

## MVP target

- `V2_BACKTEST_AND_PAPER_MVP_READY`.

## Planner state

- Standing down with explicit human attention surface. No further planner-driven re-emission of the corrupted task JSON will be attempted in this turn or in the next planner turn until the human applies the deterministic one-shot manual fix described in the "Manual remediation" section below.

## Discipline citation

The prior planner turn `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/PLANNER_TURN_2I_AUTHORIZE_WATCHDOG_DISPATCH_VIA_PLANNER_NOTE_EXCLUSIONS.md` ("Iteration cap discipline" section) stated verbatim: "If the supervisor's next dispatch of the watchdog still does not satisfy `git status --porcelain` cleanliness after these exclusions are applied, the deterministic next planner action is to surface to human attention rather than emit a sixth stand-down variant." The current blocker is logically equivalent — the watchdog cannot dispatch — but the underlying cause is JSON parse failure, not worktree dirtiness. The same discipline applies: surface, do not re-iterate.

## Diagnosis

The pending watchdog recovery task definition file `claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_2hc_paper_execution_ledger_composition_root_codex_go_no_go.json` has the following structure in the working tree (uncommitted modification relative to HEAD):

- Line 1 through line 117 is well-formed JSON. Line 117 is the closing `}` brace of the JSON object.
- Line 118 is the literal text `END_FILE: claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_2hc_paper_execution_ledger_composition_root_codex_go_no_go.json`. This is a planner-emission harness framing token that the harness should have stripped from the materialized file body but did not, presumably because the prior planner turn placed the token inside the BEGIN_FILE / END_FILE block instead of as the block terminator.
- Line 119 is a blank line.
- Line 120 is a long single-paragraph narrative beginning "This turn: surgical dispatch-bridge fix only. Re-emitted the pending watchdog recovery task JSON without the trailing `END_FILE:` marker leakage and without the trailing markdown fence opener that previously made the file unparseable." This narrative belongs in the planner authorship note, not in the task JSON file body.

The supervisor's pre-dispatch parser invokes `json.load` (or equivalent) on the task definition file before invoking Codex. With the literal lines 118-120 present in the file body, the parser raises `json.decoder.JSONDecodeError` and the supervisor refuses to dispatch the task. Codex is therefore never invoked, the `26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` marker body is never rewritten from `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_FAIL` to `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS`, and tasks `143_replay_backtest_runner_2ia_domain_implementation.json` and `144_replay_backtest_runner_2ia_domain_codex_review.json` cannot dispatch.

## Why the planner will not auto-retry the re-emission

The prior planner turn at `PLANNER_TURN_2I_AUTHORIZE_WATCHDOG_DISPATCH_VIA_PLANNER_NOTE_EXCLUSIONS.md` already attempted exactly this fix. Its narrative claimed: "Re-emitted the pending watchdog recovery task JSON without the trailing `END_FILE:` marker leakage and without the trailing markdown fence opener that previously made the file unparseable." The materialized result of that emission is the current corrupted file body — the trailing `END_FILE:` marker line and trailing narrative paragraph are still present. A second planner re-emission attempt has empirical evidence of likely producing the same corruption pattern, because the planner-emission machinery is producing this leakage on the watchdog task JSON specifically, while other artifacts in the same planner cycle (for example `00_PHASE_2I_SUB_PHASE_BREAKDOWN.md`, `01_PHASE_2I_LEGACY_EVIDENCE_REVIEW.md`, the 2I.A planning bundle 02-05, the `27_` reconciliation addendum, and this human-attention note itself) are materializing cleanly. The most likely cause is structural — the prior emission contained narrative text after the END_FILE marker but before the next BEGIN_FILE marker, which the harness greedily included in the file body. Without a controlled experiment proving the harness will materialize this specific file path cleanly on a fresh emission, repeating the emission is undisciplined iteration and is rejected.

## Manual remediation (one shot, deterministic, reversible)

The human operator should perform exactly the following sequence:

1. Truncate the corrupted file to its valid JSON-only prefix:

   ```bash
   cd "/home/wali/Desktop/AI BOT REBUILD"
   head -n 117 claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_2hc_paper_execution_ledger_composition_root_codex_go_no_go.json > /tmp/watchdog_task.json
   mv /tmp/watchdog_task.json claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_2hc_paper_execution_ledger_composition_root_codex_go_no_go.json
   ```

2. Validate the JSON parses:

   ```bash
   python3 -m json.tool claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_2hc_paper_execution_ledger_composition_root_codex_go_no_go.json > /dev/null && echo "JSON parses OK"
   ```

   Expected output: `JSON parses OK`. If the validator prints any error, stop and surface back; do not commit.

3. Stage and commit the corrected task definition together with the four durable planner stand-down / authorization / human-attention notes already present in the working tree as untracked files. The watchdog task's `worktree_excluded_paths` field already lists all five of these as exclusions for its dispatch precondition, so the supervisor will accept the dispatch on the next cycle. Suggested commit message: `Strip planner-emission END_FILE marker leakage from watchdog recovery task JSON`. Do not amend any prior commit.

4. After the commit, the supervisor's next dispatch cycle will parse the now-valid JSON, run the watchdog recovery task, rewrite the `26_` marker body to `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS`, emit the two `automation_reliability/codex_recover_fail_marker_2hc_..._REPORT.md` and `..._GO_NO_GO.md` recovery report files, then auto-commit those three artifacts under REQ_0016 / REQ_0021. The supervisor will then dispatch task `143_replay_backtest_runner_2ia_domain_implementation` from a clean worktree.

The truncation is reversible by `git checkout HEAD -- claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_2hc_paper_execution_ledger_composition_root_codex_go_no_go.json` if any concern arises before the commit lands. No semantic field of the JSON is changed by this manual fix; only the trailing non-JSON byte stream is stripped.

## What this planner turn does not do

- Does not author yet another re-emission of the corrupted task JSON.
- Does not author a new lane C codex_watchdog task to fix the corruption, because Codex itself cannot be dispatched while the corrupting task definition occupies its slot in the supervisor queue and because authoring a new task requires a planner re-emission of yet another JSON file with the same potential leakage failure mode.
- Does not modify any V2 source or test file.
- Does not modify any 2H.A, 2H.B, or 2H.C planning, implementation, review, reconciliation, or marker file.
- Does not modify any 2I.A planning artifact 00-05.
- Does not modify the 143 or 144 task definitions.
- Does not modify the master planner prompt at `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`.
- Does not modify the supervisor `master_rebuild_planner_status.json` file.
- Does not modify the body of any prior `PLANNER_TURN_2I_*` note.
- Does not modify the body of the `26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` marker file (the codex watchdog recovery task remains the only authorized writer of that body, and the body remains `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_FAIL` until that task succeeds).

## Logical milestone progression (unchanged)

- `PAPER_EXECUTION_LEDGER_MVP` (REQ_0017 milestone 4) remains logically CLOSED at the master-planner layer per the 24_ implementation marker, the 25_ Codex review, the 26_ Codex FAIL marker awaiting watchdog reconciliation, and the 27_ reconciliation addendum that reconciles the row-50 015A scaffold cross-isolation finding to PASS in the same fashion as the 2H.A and 2H.B precedents. The literal 26_ marker body remains `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_FAIL` pending the watchdog dispatch.
- `REPLAY_BACKTEST_RUNNER_MVP` (REQ_0017 milestone 5) remains logically OPEN. Active sub-phase is Phase 2I.A — replay/backtest runner domain (value-object surface). Tasks 143 and 144 are authored but not dispatchable until the 26_ marker reconciliation completes.
- Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` remains logically 3 milestones — `REPLAY_BACKTEST_RUNNER_MVP`, `PAPER_MODE_MVP`, `SHADOW_MODE_READINESS`.

## Lane and MVP relevance

- Lane: `codex_watchdog` (Lane C) for the diagnostic surface itself; the gated downstream beneficiary lane is `paper_backtest_mvp` (Lane A).
- MVP relevance: documents the deterministic small manual fix that, once applied by the human, lets the supervisor dispatch the watchdog recovery task, flips the 26_ marker to PASS, sweeps the related artifacts in a single durable auto-commit batch, and dispatches task 143 to begin REQ_0017 milestone 5 implementation.
- Blocked by: planner-emission corruption in `claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_2hc_paper_execution_ledger_composition_root_codex_go_no_go.json` lines 118-120; resolution requires a one-line truncation by the human operator as specified in the "Manual remediation" section.
- Next gate: after the manual fix and commit, `CODEX_FAIL_MARKER_RECOVERY_READY` at `claude_worklog/phase2_core_rebuild/automation_reliability/codex_recover_fail_marker_2hc_paper_execution_ledger_composition_root_codex_go_no_go_GO_NO_GO.md`, then `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS` at `26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`, then `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPL_AND_VALIDATION_PASSED` at `07_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_GO_NO_GO.md` after task 143 runs, then `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_PASS` at `09_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_GO_NO_GO.md` after task 144 runs.
- Legacy evidence consulted: `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/24_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_GO_NO_GO.md`, `25_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_REVIEW.md`, `26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`, `27_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md`, `10_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_RECONCILIATION_ADDENDUM.md`, `18_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md`, `19_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_RECONCILIATION_ADDENDUM.md`; the 2I.A planning bundle `00..05`; the 143 and 144 task definitions; the corrupted body of the watchdog recovery task definition itself read at lines 1-121 to confirm the exact corruption locus; the four prior `PLANNER_TURN_2I_*` notes establishing the deadlock-and-iteration-cap history.
- Legacy failure addressed: same legacy automation-reliability failure already named in the prior planner turn — the legacy bot system required manual human intervention to clean dirty worktrees and to reconcile fail-marker recovery loops. The specific sub-failure addressed by this surface-to-human-attention turn is that the planner-emission machinery is producing END_FILE marker leakage on a specific re-emission target, and the planner has no observable mechanism to verify a given emission materialized cleanly without a full git diff against the prior committed state. Empirically, the prior re-emission failed; per the planner's own iteration-cap discipline, the correct response is to surface and request a one-line manual fix rather than re-iterate.

## Hard safety reaffirmation

This turn:

- did not modify `/home/wali/Desktop/AI BOT`
- did not read or write any literal `red`+`is` key
- did not invoke any `red`+`is` command at any time
- did not restart any live trainer, trader, orchestrator, ingestor, or `red`+`is` service
- did not place, cancel, or modify any exchange order
- did not change leverage or margin
- did not enable live trading
- did not deploy or release to any environment
- did not run any production migration
- did not expose or commit any credential
- did not request L4 or L5 authority
- did not approve any live gate
- did not modify any file under `v2/backend/app/`
- did not modify any file under `v2/backend/tests/`
- did not modify any 2H.A, 2H.B, or 2H.C planning, implementation, review, reconciliation, or marker file
- did not modify the body of `26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`
- did not modify any 2I.A planning artifact 00-05
- did not modify any 2G, 2F, 2E1, 2E2, or 2E3 artifact
- did not modify the body of any prior `PLANNER_TURN_2I_*` note
- did not modify the master planner prompt at `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`
- did not modify the supervisor `master_rebuild_planner_status.json` file
- did not author any new task definition
- did not modify any existing task definition file body, including the corrupted `claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_2hc_paper_execution_ledger_composition_root_codex_go_no_go.json` (manual fix is delegated to the human per the "Manual remediation" section)
- did not introduce any new lineage ID at the 2I.A value-object layer beyond those documented in `02_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_SPEC.md`
- did not introduce any FastAPI surface, adapter expansion, ledger persistence, PnL, sizing, quantity, price, fees, slippage, GPU, checkpoint, model-loading subsystem, replay engine, scheduler, or background loop in any artifact

Final live approval remains human-only. Live trading remains BLOCKED.

PLANNER_TURN_2I_HUMAN_ATTENTION_REQUIRED_WATCHDOG_TASK_JSON_END_FILE_LEAKAGE_BLOCKS_DISPATCH_READY
```

Planner stand-down with human attention surface. The watchdog task JSON at `claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_2hc_paper_execution_ledger_composition_root_codex_go_no_go.json` has trailing `END_FILE:` marker leakage at line 118 plus a trailing narrative paragraph at line 120, making the JSON unparseable and blocking supervisor dispatch. The prior planner turn already attempted this re-emission and reproduced the corruption; per its own iteration-cap discipline, the deterministic next action is to surface, not re-iterate. The single-line manual fix is `head -n 117 ... > tmp && mv tmp ...`, validated with `python3 -m json.tool`, committed alongside the four already-untracked planner notes. Once committed, the supervisor will dispatch the watchdog, the 26_ marker flips to PASS, and task 143 dispatches to open `REPLAY_BACKTEST_RUNNER_MVP` (REQ_0017 milestone 5).
