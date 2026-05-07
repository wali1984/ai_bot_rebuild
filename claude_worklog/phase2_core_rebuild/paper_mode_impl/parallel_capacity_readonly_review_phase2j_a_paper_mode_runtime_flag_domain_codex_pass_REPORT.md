# Parallel Read-Only Review: Phase 2J.A Paper-Mode Runtime Flag Domain

## Verdict

READY with recommendations. No source blocker found in the committed 2J.A milestone.

The committed milestone is compatible with the paper/backtest MVP as a narrow domain-only value object: it adds a frozen, slotted runtime flag; exposes only the domain error, value object, and two non-live mode constants; rejects unknown/live-enabled modes; and requires the live-blocked posture to be true. It does not introduce execution, persistence, Redis, FastAPI, clocks, schedulers, order placement, live-readiness flips, or paper executor behavior.

## Review Scope

Read-only review only. I inspected the committed marker, milestone planning artifacts, implementation report, Codex review, committed source, committed tests, current relevant-scope diff, and task metadata. I did not patch files, did not run tests that could create cache artifacts, did not write Redis, did not touch legacy runtime state, did not restart services, and did not place/cancel orders.

## Paper/Backtest MVP Compatibility

PASS. The implementation is deliberately small enough for the MVP path:

- The runtime mode is typed rather than inferred from environment or process-global state.
- The default intended mode remains paper.
- The only alternate mode is an explicit live-blocked posture, not live enablement.
- Both allowed modes require live execution to remain blocked.
- There is no PnL, sizing, fill, fee, slippage, ledger, replay, scheduler, API, adapter, or strategy behavior in this domain layer.

This is appropriate for 2J.A because paper/backtest execution behavior belongs in later assembler/composition milestones, not in the value object.

## Risk-Gateway Handoff Completeness

PARTIAL BY DESIGN, not a blocker for 2J.A.

The domain object can be consumed by a future risk-gateway handoff because it gives downstream code a typed and exhaustive signal that live execution remains blocked. However, this milestone does not yet prove the handoff end to end:

- No assembler service binds requested runtime mode to the flag.
- No composition runtime injects the flag into the decision flow.
- No risk-gateway service input requires the flag.
- No risk decision payload records the flag value.
- No negative integration test proves risk-gateway denial when the flag is absent or invalid.

Recommendation for 2J.B/2J.C: make the runtime flag an explicit input or captured dependency at the service/composition boundary that hands off to risk evaluation, and add tests proving no risk-approved paper decision can be assembled without a valid flag whose live-blocked value is true.

## Lineage And Explainability Gaps

No 2J.A blocker. The planning artifacts explicitly avoid creating a new lineage ID at the value-object layer, which is correct for a pure runtime flag.

Remaining downstream gap: the current flag has no direct lineage/explainability carrier. Later milestones should make the flag observable in decision evidence without turning it into a new lineage node. Recommended hardening:

- Include mode and live-blocked posture in paper decision/risk decision explainability payloads.
- Preserve the timestamp from the flag as evidence of when the posture was emitted.
- Ensure paper trade, replay run, and future shadow decision records can explain whether the runtime was paper or live-blocked at decision time.
- Add tests that stale or missing runtime-flag evidence is visible in explainability output and cannot silently default to live behavior.

## Stale Evidence

One stale-evidence issue found, non-blocking.

The prior Codex review recorded a clean worktree at dispatch time. The current worktree is no longer clean due to unrelated dirty/untracked supervisor/planner artifacts. The relevant committed 2J.A source, tests, and pass marker have no current diff from HEAD, so this does not invalidate the reviewed milestone. Future reports should avoid relying on an old clean-worktree statement as current evidence and should record both dispatch-time and review-time status.

## Test-Hardening Recommendations

Recommended additions for follow-on milestones:

- Re-run the 2J.A unit suite in CI with bytecode/cache writes disabled or isolated, so read-only reviewers can reproduce without touching the worktree.
- Add a test that an omitted live-blocked argument cannot be constructed by defaults, preserving the no-default field contract.
- Add non-string mode cases beyond empty/uppercase/live strings, such as None, bool, and numeric values.
- Add timestamp boundary coverage for zero and a large positive integer.
- Add an assembler-level test that every non-paper/non-live-blocked synonym fails before a flag is produced.
- Add composition-level tests proving the clock is called exactly once per emitted flag and is not called at build/import time.
- Add risk-gateway integration tests proving missing, stale, false, or unrecognized runtime-mode evidence blocks approval.
- Add explainability tests proving runtime mode appears in downstream paper/backtest evidence payloads.

## Blockers

None for the committed 2J.A milestone.

## Recommendation

CODEX_PARALLEL_READONLY_REVIEW_READY
