# CLAUDE — Expand V2 Risk Gateway Parity Tests From Legacy Action-Path Map — REPORT

Task ID: `claude_expand_v2_risk_gateway_test_suite_from_legacy_action_map`
Date: 2026-05-14
Operator: Wali (AI BOT V2 Master Non-Live Rebuild Planner)
Live gate: `blocked_human_only`
Final approval token: `absent`
Status: **BLOCKED_OR_REMEDIATED — V2_ENV_BLOCKED / MISSING_EVIDENCE**

## 1. Scope

The task requires expanding V2 risk gateway parity tests from the legacy
action-path map (`claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/trader_risk_action_path_map.json`)
to cover nine legacy gates:

1. kill switch
2. halt manager
3. reduce-only latch
4. intelligent close guard
5. auto deleverager
6. shared risk budget (`shared_risk_gate` / `risk_budget_allocator`)
7. margin governor
8. phase controller
9. adaptive microstructure toxicity (`adaptive_gate` over `microstructure_toxicity`)

The hard rule: "Tests must invoke real V2 gate functions and must not skip."

## 2. Current V2 risk-gateway surface (raw evidence)

V2 service module: `v2/backend/app/services/risk_gateway/service.py`
- Only public function: `assemble_risk_decision_record(decision, now_ms_clock) -> RiskDecisionRecord`
- Decision branching covers exactly four `decision.decision_action` values:
  `open_long`, `open_short`, `hold`, `abstain`.
- Output reason codes are limited to:
  `allow_proceed_long`, `allow_proceed_short`, `deny_orchestrator_held`, `deny_orchestrator_abstained`.
- The record forces `live_blocked=True` unconditionally.

V2 domain module: `v2/backend/app/domain/risk_gateway/record.py`
- `_ALLOWED_RISK_REASONS` = {allow_proceed_long, allow_proceed_short, deny_orchestrator_abstained, deny_orchestrator_held, deny_default}.
- No kill-switch, halt, reduce-only, ADL, margin-governor, phase-controller, micro-toxicity, or budget reason codes are defined.

There is **no V2 callable** in `v2/backend/app/services/risk_gateway/` or
`v2/backend/app/domain/risk_gateway/` that exercises any of the nine legacy gates.
Every legacy gate file referenced by `trader_risk_action_path_map.json`
exists only as a preserved read-only snapshot under
`v2/legacy_preserved/full_runtime_closure/risk/` and is forbidden from
direct import per `CLAUDE.md` "Protected Runtime Policy" and the
read/write boundaries.

## 3. Dependency closure status

Reference: `claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/v2_parity_gap_matrix.json`

```
v2_risk_gateway_runtime_worker → PARTIALLY_MIGRATED_NEEDS_TEST
legacy_files                   → risk/*.py (22), trading/depth_execution_gate.py,
                                  trading/fee_ratio_gate.py, trading/adaptive_edge_gate.py
fully_migrated_count_is_zero_reason →
  "no V2 worker carries a LEGACY_BASELINE_ANALYSIS.md that cites SHA256 from
   the just-produced full_runtime_copied_source_manifest.json AND enumerates
   every legacy responsibility from Phases D/E/F"
live_gate_implication → must_remain_blocked_human_only
```

Dependency closure for the nine legacy gate files is recorded in
`full_runtime_copied_source_manifest.json` (UNCHANGED status, safe_to_commit=true)
and v2-preserved at `v2/legacy_preserved/full_runtime_closure/risk/`.
No closure gap exists for the legacy artefacts themselves — the gap is
that **no V2 callables have been written that wrap or replicate them**.

## 4. Why tests cannot be expanded without skips

The task's hard constraint: "Tests must invoke real V2 gate functions and
must not skip."

To honour that constraint, the V2 codebase would need, at minimum:

| Legacy gate                       | Required V2 callable (absent)                                          |
|-----------------------------------|------------------------------------------------------------------------|
| kill_switch                       | `services.risk_gateway.kill_switch.evaluate_kill_switch_state`         |
| halt_manager                      | `services.risk_gateway.halt_manager.evaluate_halt_state`               |
| reduce_only_latch                 | `services.risk_gateway.reduce_only_latch.evaluate_latch_state`         |
| intelligent_close_guard           | `services.risk_gateway.intelligent_close_guard.evaluate_close_guard`   |
| auto_deleverager                  | `services.risk_gateway.auto_deleverager.evaluate_adl_state`            |
| shared_risk_budget                | `services.risk_gateway.shared_risk_gate.evaluate_budget_state`         |
| margin_governor                   | `services.risk_gateway.margin_governor.evaluate_margin_state`          |
| phase_controller                  | `services.risk_gateway.phase_controller.evaluate_phase_gate`           |
| adaptive_microstructure_toxicity  | `services.risk_gateway.adaptive_gate.evaluate_toxicity_block`          |

Domain prerequisites (also absent): per-gate reason-code constants in
`v2/backend/app/domain/risk_gateway/record.py`'s `_ALLOWED_RISK_REASONS`
allowlist (`deny_kill_switch_active`, `deny_halt_manager_active`,
`deny_reduce_only_latch`, `allow_close_only_intelligent_close_guard`,
`deny_auto_deleverager_triggered`, `deny_shared_risk_budget_exhausted`,
`deny_margin_governor_leverage_increase_blocked`,
`deny_phase_controller_warmup`, `deny_adaptive_microstructure_toxic`).

Without those callables and reason codes, any added parity test must
either (a) import legacy code directly (forbidden — protected runtime
policy / read/write boundary), (b) skip (forbidden by task), or
(c) assert against constants that do not exist (would not invoke a
"real V2 gate function" as required).

Therefore: **MISSING_EVIDENCE / V2_ENV_BLOCKED**. No tests are written
in this task. A remediation plan is captured below so the next CODEX or
CLAUDE task can unblock the test expansion.

## 5. Legacy baseline analysis

See `claude_expand_v2_risk_gateway_test_suite_from_legacy_action_map_LEGACY_BASELINE_ANALYSIS.md`
in this folder for the full SHA-cited analysis of the nine legacy gate
files and the test-expansion contract they impose on V2.

## 6. Legacy behaviour mapping

See `claude_expand_v2_risk_gateway_test_suite_from_legacy_action_map_legacy_behavior_mapping.json`
for the per-gate behaviour mapping (legacy file → legacy SHA256 →
required V2 callable → required reason code → required parity test name).

## 7. Public payload impact

None. This task neither creates final-approval tokens, Redis trim
approvals, nor live-gate flips. `live_gate=blocked_human_only` and
`live_symbols=[]` remain unchanged. No V2 runtime payload is mutated.

## 8. Tests added

**Zero.** The current task is BLOCKED_OR_REMEDIATED with classification
**V2_ENV_BLOCKED / MISSING_EVIDENCE** because no V2 gate callables exist
to invoke. Adding skipped tests is explicitly forbidden by the task
contract.

## 9. Remediation plan for unblocker (next agent)

Before parity tests can be expanded:

1. Codex/Claude port task: create domain reason codes for each of the
   nine gates in `v2/backend/app/domain/risk_gateway/record.py`.
2. Codex/Claude port task: create service modules under
   `v2/backend/app/services/risk_gateway/<gate>.py` each exposing
   one pure function `evaluate_<gate>_state(...) -> RiskDecisionRecord`
   that does not import legacy code and is wired into
   `assemble_risk_decision_record` as an ordered gate-stack.
3. Codex/Claude port task: SHA-citation update inside each new module's
   header docstring linking the new V2 file back to the legacy SHA256
   in `full_runtime_copied_source_manifest.json`.
4. After (1)–(3) merge, this test-expansion task can be re-dispatched
   and will produce real, non-skip tests under
   `v2/backend/tests/unit/composition/risk_gateway/` and
   `v2/backend/tests/integration/risk_gateway/` invoking the new
   functions.

## 10. GO/NO-GO

**NO-GO** for test expansion in this task cycle.
**GO** for emitting BLOCKED_OR_REMEDIATED status, legacy baseline
analysis, and legacy behavior mapping so the next porting task starts
with full evidence on the table.
