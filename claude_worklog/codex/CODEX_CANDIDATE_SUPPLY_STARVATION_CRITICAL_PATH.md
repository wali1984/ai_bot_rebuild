# CODEX HANDOFF — Candidate-Supply Starvation is the Guardian Critical Path

Author: Claude main session (read-only runtime audit; independent of Codex fix lane)
Date: 2026-07-19 (UTC; guardian check 2026-07-19T02:06Z / paper loop restarted 2026-07-18 20:45 EDT)
Method: READ-ONLY. No code edits, no Redis writes, no process changes. Live gate BLOCKED throughout.
Lane: Codex trainer + preemptive-edge-control (candidate supply). NOT a frontend/allocator-only issue.

## TL;DR
The paper loop is up and running your **uncommitted** allocator/preemptive rework, but it is taking
**zero trades** because it has **zero candidate supply**. Every guardian red gate (G10/G11/G12/G13/G14)
is therefore frozen on the same 92 stale bad-historical trades — the capital-invariant fix cannot be
proven, and expectancy/PF cannot recover, until the loop actually trades new closes. **Candidate supply
is the #1 unblock, upstream of everything else.**

## Raw evidence (all read-only, reproducible)

**Claim 1 — Loop is running your in-flight fix but has 0 activity.**
- Service: `ai-bot-v2-trade-management-paper-loop.service` = `active (running) since Sat 2026-07-18 20:45:21 EDT`, PID 1816509, cmd `v2.backend.app.cli.v2_trade_management_paper_loop --loop`.
  (systemd runs from the repo working tree → it imports your UNCOMMITTED allocator/preemptive changes.)
- Redis `v2:paper:heartbeat` → `{"open_position_count": 0, "closed_trade_count": 92}`.
- Redis `v2:paper:closed_trades` (string JSON) → 92 rows, **0 with an exit timestamp after the 20:45 restart**.
- Verify: `systemctl --user status ai-bot-v2-trade-management-paper-loop.service`; read Redis key
  `v2:paper:heartbeat` (GET, JSON) and count `v2:paper:closed_trades`.

**Claim 2 — Root cause is candidate starvation, not the allocator.** From `/api/v2/paper/status`:
- `summary.intents_accepted = 0` AND `summary.intents_blocked = 0` → nothing even reaches the loop to evaluate.
- `real_trader_readiness.exact_no_live_reason = A_GRADE_SUPPLY_ZERO`
- `a_grade_blocker_truth.a_grade.closest_gap_reason = NO_A_GRADE_RUNTIME_SUPPLY`
- `a_grade_blocker_truth.preemptive.candidate_count = 0`
- `a_grade_blocker_truth.paper_learning_feeder.fresh_exploration_candidates = 0`
- `a_grade_blocker_truth.paper_learning_feeder.exact_no_fill_reason = NO_CURRENT_EXPLORATION_CANDIDATES`
- Verify: `curl -s localhost:8000/api/v2/paper/status` and inspect the `a_grade_blocker_truth` object.

**Claim 3 — Exploration is ENABLED yet emits nothing (this is a generator bug, not a flag).**
- `systemctl --user show ai-bot-v2-trade-management-paper-loop.service -p Environment` →
  `PAPER_BOOTSTRAP_EXPLORATION_ENABLED=true`.
- Despite the flag being ON, `fresh_exploration_candidates = 0` and `preemptive.candidate_count = 0`.
- → The exploration/preemptive candidate GENERATOR is not producing candidates. This lives in your
  uncommitted `v2/backend/app/services/preemptive_edge_control/decision.py` (+885 lines in the working tree).

**Claim 4 — Your capital-invariant rework is in-flight and 1 test short of green.**
- Uncommitted: 4,329 insertions across 16 files (`allocator.py` +1601, `decision.py` +885,
  `position_state.py` +517, `outcome_memory_updater.py` +445, `dynamic_envelope.py` +425,
  `adaptive_cost_model.py` +382, `counterfactual.py` +246, …).
- Test health of the working tree: allocator+leverage lane 137/137 green; broader ptm/edge lane 220/221,
  with **1 red**: `test_lifecycle.py::test_position_from_fill_sets_policy_activated_at_for_adaptive_policy`
  (expects `policy_activated_at == 2026-06-11T10:00:05Z`, got `...10:00:00Z` — a 5s activation-timestamp
  semantics gap).
- Verify: `.venv/bin/pytest "v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py::test_position_from_fill_sets_policy_activated_at_for_adaptive_policy" -q`

**Claim 5 — Guardian is frozen on stale data because of Claim 2.** 10/16 pass; red = G03/G10/G11/G12/G13/G14.
- G10 = 46 capital-invariant violations, ALL on pre-fix historical rows (20 subclass-A `allocated_margin==0`,
  26 subclass-B accumulation-freeze); G13 = -18.126 notional-weighted bps; G14 = PF 0.658 — all computed on
  the frozen 92-trade set. No new closes → no recovery signal.

## Already landed (context — do not redo)
- `ed115ac695` fix(paper): make leverage continuous and side-aware  (my CODEX_PER_SYMBOL_LEVERAGE_ENVELOPE_HANDOFF)
- `a87029321d` feat(trainer): enforce causal on-policy learning provenance  (my CODEX_PPO_ON_POLICY_STARVATION_FINDING)
- `2db3fffd43` fix(paper): restore side-aware liquidation exit (CG-F049 area)

## What Codex needs to do (priority order)

**P1 — Restore candidate supply (THE critical path; without this, nothing downstream can recover).**
Two independent sources; either one gets the flywheel turning, both is better:
  a. **Exploration feeder** — the enable flag is ON but the generator emits 0.
     Trace why `preemptive_edge_control/decision.py` yields `NO_CURRENT_EXPLORATION_CANDIDATES` /
     `candidate_count=0` even with exploration enabled. Likely suspects in the uncommitted rework:
     a stricter admission predicate, an empty upstream candidate pool (features/ta_closed inputs),
     or the exploration branch not being reached. Keep ALL hard gates (positive-EV floor, bounded loss,
     never A+ / never real-trading) — the goal is bounded exploration to generate training data, per
     project_paper_cold_start_exploration.
  b. **A-grade supply from the trainer** — `A_GRADE_SUPPLY_ZERO` because the model is INFERENCE_ONLY
     (promotion rejected). This is the CG-F053 edge problem + the PPO on-policy unblock (a87029321d is
     committed; confirm `ppo_on_policy_rows` is actually climbing from ~0 and that a candidate can now
     earn positive PIT-safe post-cost edge to leave INFERENCE_ONLY).

**P2 — Land the allocator/capital-invariant rework.** Fix the 1 red lifecycle test (Claim 4), then commit
the 16-file / 4,329-line working set so G10's ENTRY-side invariant is provable on new closes and the
guardian stops flagging "81 files uncommitted" (WQ-R34 gating_next_step #1).

**P3 (operator, not Codex) — G10 historical repair.** After P1/P2 produce new coherent closes, the operator
authorizes `tools/g10_capital_invariant_repair.py` for the 46 pre-fix rows (reversible, G08-safe).

## Acceptance (how we'll know it worked)
1. `fresh_exploration_candidates > 0` OR `preemptive.candidate_count > 0` in `/api/v2/paper/status`.
2. `summary.intents_accepted` climbs above 0; NEW rows appear in `v2:paper:closed_trades` with exit
   timestamps after restart.
3. Those new closes satisfy `gross_notional_usd ≈ allocated_margin_usd × effective_leverage` (±$0.02) —
   the runtime proof of F050 that WQ-R34 needs.
4. G13/G14 recompute on the new closes (not the stale 92); expectancy trends toward positive.

## Cross-refs
- claude_worklog/guardian_runtime_validation/CG_F049_F050_RUNTIME_VALIDATION_2026_07_17.md (WQ-R34, refreshed 2026-07-18T22:14Z)
- claude_worklog/codex/CODEX_PPO_ON_POLICY_STARVATION_FINDING.md (P1b upstream)
- claude_worklog/codex/CODEX_PER_SYMBOL_LEVERAGE_ENVELOPE_HANDOFF.md (landed)
- Memory: project_paper_cold_start_exploration, project_agrade_binding_constraint, project_trainer_inference_only_deadlock_fix

## Confidence & missing evidence
- Confidence HIGH that candidate supply is the binding constraint: `intents_accepted=0 AND intents_blocked=0`
  is unambiguous — the loop receives nothing to act on.
- Missing evidence I could NOT gather read-only: the exact code path in the uncommitted `decision.py` that
  suppresses exploration candidates (would require reading Codex's in-flight file, which is Codex's lane),
  and whether `ppo_on_policy_rows` is climbing post-a87029321d (not surfaced in `/api/v2/paper/status`).
