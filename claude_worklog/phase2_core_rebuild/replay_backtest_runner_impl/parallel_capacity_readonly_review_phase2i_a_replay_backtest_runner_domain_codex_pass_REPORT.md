# Codex Parallel Read-Only Review - Phase 2I.A Replay/Backtest Runner Domain Codex Pass

## Scope

Read-only parallel review of committed milestone `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_PASS`.

No source files were patched. No dirty work was modified. No legacy bot tree was touched. No Redis writes, service restarts, order placement, order cancellation, or live-trading enablement were performed.

Current worktree state was dirty before and after review: one modified planner prompt and one untracked supervisor task artifact were present. These were not changed by this review.

## Current Validation Evidence

Fresh read-only validation was run against the current workspace:

- Domain package compile check: passed with no output.
- Replay/backtest runner domain unit suite: `51 passed`.
- Adjacent domain regression suites for paper ledger, risk gateway, orchestrator decision, and trainer prediction output: `127 passed`.
- Forbidden-token scan over the replay/backtest domain source returned no matches for Redis, HTTP, FastAPI, subprocess, wall-clock, environment, persistence, PnL, scheduler, background-loop, or executor tokens.

## Paper/Backtest MVP Compatibility

GO for paper/backtest MVP value-object compatibility.

The domain is additive and pure. It defines frozen, slotted run, step, and summary records with no I/O, model calls, Redis imports, HTTP clients, FastAPI registration, schedulers, executors, persistence, PnL, price, quantity, fee, or slippage logic.

`live_blocked` is mandatory and must be `True` across run, step, and summary records. There is no source-level default path to `False`.

Replay and backtest run modes are explicit and bounded to `replay` and `backtest`, which is sufficient for the current MVP layer.

## Risk-Gateway Handoff

GO with non-blocking hardening recommendations.

The step record preserves the required lineage chain through paper trade, risk decision, orchestrator decision, prediction, feature snapshot, and symbol identifiers. It also mirrors paper-ledger action and reason into replay-step action and reason codes.

The handoff is complete for the planned assembler layer because the assembler spec derives steps from a validated paper ledger entry, which already sits downstream of the risk gateway. The domain intentionally avoids importing risk-gateway or paper-ledger records, which keeps the value-object layer isolated.

Non-blocking gap: the replay step does not carry the original risk action and risk reason as first-class fields. It can still recover the chain through `risk_decision_id`, but immediate explainability at replay-step level depends on joining back to risk/paper-ledger evidence. This is acceptable for 2I.A, but the assembler/composition layers should make that join requirement explicit in report output or API responses.

## Lineage And Explainability

GO with follow-up recommendation.

The core lineage IDs are present and validated as non-empty, whitespace-free, bounded strings. The summary record validates count partitions, which supports explainable aggregate replay outcomes.

The main explainability gap is qualitative: the domain records mirrored reason codes but not a free-form explanation, policy version, threshold snapshot, or reason text. That is consistent with the 2I.A value-object cap, but downstream layers should expose enough joined evidence to explain why each replay step was allowed or denied.

## Stale Evidence

No blocker.

The prior Codex review artifact reported a clean worktree at that earlier review point. The current workspace is dirty, but the dirt is unrelated to the reviewed domain source and remained unchanged.

Some planner notes contain older commit/status context. Fresh validation on the current workspace supersedes that stale planning evidence for this review.

## Test-Hardening Recommendations

Recommended before later MVP closeout, not blocking this pass:

- Add domain rejection tests for bool values on all timestamp/count integer fields, not only the existing sampled bool case.
- Add boundary-success tests at exact max identifier lengths for run, step, and summary IDs.
- Add symbol boundary tests for empty, whitespace, too-long, and valid max-length uppercase symbols across all three records where applicable.
- Add direct tests for all step identifier fields, not only sampled step IDs.
- In the assembler phase, require tests that prove no caller-provided `live_blocked` can enter constructed records and that lineage propagation remains complete across all five paper-ledger reason branches.

## Finding

No blocking issue found for Phase 2I.A Codex pass readiness.
