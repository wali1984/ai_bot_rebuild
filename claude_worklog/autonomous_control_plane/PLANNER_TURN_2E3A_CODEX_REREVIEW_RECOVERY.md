# Planner Turn — 2E3.A Codex Re-Review Recovery

## Trigger

`186_2E3A_PREDICTION_OUTPUT_DOMAIN_CODEX_GO_NO_GO.md` =
`PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_CODEX_FAIL`.

## Codex review summary

`185_2E3A_PREDICTION_OUTPUT_DOMAIN_CODEX_REVIEW.md` shows 26 of 27
rubric rows PASS. The single FAIL is rubric row 23 (cross-isolation
`git status -s`). Pytest is green for all six required suites
(`trainer_prediction_output` 31/31, `trainer_worker_health` domain
28/28, `trainer_worker_health` services 22/22, `trainer_worker_health`
composition 20/20, `trainer_liveness` 52/52, `trainer_parity` services
34/34 and composition 25/25). `py_compile` is clean. Forbidden-token
scans return zero matches across the three authored source files.
Secret-shaped-string scans return zero matches.

## Root cause of the FAIL

`git status -s claude_worklog/autonomous_control_plane/` returns
`M claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`.
`181_PHASE_2E3A_PREDICTION_OUTPUT_DOMAIN_SAFETY_BOUNDARIES.md` lists
`claude_worklog/autonomous_control_plane/` as a forbidden cross-isolation
path for the 2E3.A milestone, so any modified file under that prefix
fails rubric row 23 even when the V2 source/tests are clean.

The dirty file is the master planner prompt itself, organically grown
to incorporate `REQ_0007` through `REQ_0019`, the Claude Code Max 20x
profile block, the Codex Pro parallel lane, and the REQ_0018 planner
lane lock. The diff is non-live planner-prompt content only.
`git diff --stat` reports `1 file changed, 1314 insertions(+)` and the
diff body adds requirement-text blocks and profile/lane policy text.
No V2 source/test file, no Redis key, no legacy file, no exchange
adapter, no secret string is touched.

## Decision

Open one consolidated Codex watchdog recovery task under
`REQ_0014` / `REQ_0015` / `REQ_0016` lane `codex_watchdog`. The task
verifies the dirty file is the planner prompt only, runs a
high-confidence secret scan over the diff, commits the planner prompt
as a durable non-live artifact, pushes, and verifies that
`git status -s claude_worklog/autonomous_control_plane/` returns zero
lines. Once that recovery passes, the supervisor re-dispatches
`111_trainer_parity_2e3a_prediction_output_domain_codex_review.json`
unmodified. With cross-isolation now clean and the V2 source/tests
already green, rubric row 23 will flip to PASS and the Codex re-review
will emit
`PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_CODEX_PASS`.

## Lane discipline (REQ_0018)

- `lane`: `codex_watchdog`
- `mvp_relevance`: Clears the only Codex blocker on 2E3.A so the
  Paper/Backtest MVP path can advance into 2E3.B (trainer prediction
  record assembler service) — the next REQ_0017 / `TRAINER_PREDICTION_OUTPUT_MVP`
  sub-milestone before `ORCHESTRATOR_DECISION_MVP`.
- `next_gate`: `PHASE2E3A_PLANNER_PROMPT_DIRTY_TREE_RECOVERY_PASS`,
  followed by `PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_CODEX_PASS`
  on the re-dispatched 111.
- `blocked_by`: `git status -s claude_worklog/autonomous_control_plane/`
  must return zero lines.

## What this turn does NOT do

- Does NOT modify `v2/backend/app/domain/trainer_prediction_output/`.
- Does NOT modify any 2E3.A test file.
- Does NOT modify task 111's prompt or rubric.
- Does NOT open 2E3.B before the re-dispatched 111 returns Codex PASS.
- Does NOT touch checkpoint/GPU/model-loading/service/composition/
  adapter scope (REQ_0017 cap holds).
- Does NOT touch `/home/wali/Desktop/AI BOT`.
- Does NOT read or write any Redis key.
- Does NOT restart any live service.
- Does NOT place or cancel any exchange order.
- Does NOT enable live trading.

## Sequencing after recovery

1. Codex watchdog runs `112` (this turn's new task).
2. Watchdog commits/pushes the planner prompt and emits `187` + `188`.
3. Supervisor reconciliation tick re-dispatches existing `111`.
4. `111` re-evaluates rubric row 23 — now PASS — and emits
   `PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_CODEX_PASS` in `186`.
5. Planner opens 2E3.B in a fresh consolidated milestone turn.

PHASE2E3A_CODEX_REREVIEW_RECOVERY_PLANNER_TURN_READY
