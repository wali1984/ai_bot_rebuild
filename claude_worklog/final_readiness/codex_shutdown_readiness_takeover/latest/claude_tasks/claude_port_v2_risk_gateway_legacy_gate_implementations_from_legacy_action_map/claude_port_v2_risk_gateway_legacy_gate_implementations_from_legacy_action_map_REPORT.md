# CLAUDE_PORT_V2_RISK_GATEWAY_LEGACY_GATE_IMPLEMENTATIONS_FROM_LEGACY_ACTION_MAP — REPORT

- task_id: claude_port_v2_risk_gateway_legacy_gate_implementations_from_legacy_action_map
- date: 2026-05-14
- repo: /home/wali/Desktop/AI BOT REBUILD
- branch: master
- live_gate: blocked_human_only
- live_symbols: []
- final_approval_token: absent
- redis_trim_approval_token: absent

## Scope (per task brief)

Implement minimal fail-closed paper/shadow parity callables for the nine V2 risk-gateway legacy gates so parity tests can exist. Wire nothing to runtime; do not mutate exchange, leverage, margin mode, old Redis keys, or live trading. Cite legacy SHA256 from the preserved full-runtime closure.

Nine gates required (V2 callable / legacy module / preserved SHA256):

| # | V2 callable                  | Legacy module                              | SHA256 |
|---|------------------------------|--------------------------------------------|--------|
| 1 | evaluate_kill_switch_state   | risk/kill_switch.py                        | bf730c6fa425097aa0c246dfbab88e4f8d158afdd606a905c8f9e3c7695df59e |
| 2 | evaluate_halt_state          | risk/halt_manager.py                       | 49504d73a9fef319eb0ac6282d571492714a62526bc1c9849148685ad7eac314 |
| 3 | evaluate_latch_state         | risk/reduce_only_latch.py                  | e0dc68486a5cc2fa0fc0ea1d1197f66373f8c090deb889a403257e187c7ac611 |
| 4 | evaluate_close_guard         | risk/intelligent_close_guard.py            | 7edf6d5eca3e8654bc17f0fad22831e4daedb411138d576904a29ab0a352c3ee |
| 5 | evaluate_adl_state           | risk/auto_deleverager.py                   | 76652e99ec0b0717a3bfea887c25f78746df7765ba3f5e4eff6a21d0e820a377 |
| 6 | evaluate_budget_state        | risk/shared_risk_gate.py                   | 62c2403f2cf2ce5dec71522b919f1db6a2f6908e338903e359e021c75c59dd7f |
| 7 | evaluate_margin_state        | risk/margin_governor.py                    | e8448d2ee70697a97fbb4af27555adabe2af590d8185ebfc644b965070376eee |
| 8 | evaluate_phase_gate          | risk/phase_controller.py                   | ecd566ca7537551a9e6e267da4880a41764d346a1d43137d4088003951211ee1 |
| 9 | evaluate_toxicity_block      | risk/microstructure_toxicity.py            | 5103e3078e15734eaca310e9ae58dd8e89725ebf4317a98313f078c8bd74beef |

Companion (referenced by margin/shared_risk_gate sizing): `risk/adaptive_gate.py` SHA256 `a5057ea4ad4542881a6ebf14b9d789cbeed7873fc763c9d74d06c7c781674bce` — not a primary gate; documented for completeness in the legacy baseline analysis but not exposed as a V2 callable in this cycle.

## What was added

New service namespace (no existing module mutated):

- `v2/backend/app/services/risk_legacy_gates/__init__.py`
- `v2/backend/app/services/risk_legacy_gates/errors.py`
- `v2/backend/app/services/risk_legacy_gates/inputs.py`
- `v2/backend/app/services/risk_legacy_gates/verdict.py`
- `v2/backend/app/services/risk_legacy_gates/evaluators.py`

Public V2 callables (real, importable, not stubs):

- `evaluate_kill_switch_state(state, *, now_ms_clock)`
- `evaluate_halt_state(state, *, now_ms_clock)`
- `evaluate_latch_state(state, *, now_ms_clock)`
- `evaluate_close_guard(state, *, now_ms_clock)`
- `evaluate_adl_state(state, *, now_ms_clock)`
- `evaluate_budget_state(state, *, now_ms_clock)`
- `evaluate_margin_state(state, *, now_ms_clock)`
- `evaluate_phase_gate(state, *, now_ms_clock)`
- `evaluate_toxicity_block(state, *, now_ms_clock)`

Each callable returns a frozen `LegacyGateVerdict` carrying:
- `gate_name`
- `action` ∈ {`"allow"`, `"deny"`, `"close_only"`}
- `reason_code` (V2 reason taxonomy; allow-prefix / deny-prefix / close_only-prefix enforced)
- `legacy_source_path`
- `legacy_source_sha256`
- `evaluated_at_ms`
- `live_blocked = True` (validated invariant — fail-closed; cannot be `False`)

All evaluators are pure functions. None read from Redis, none touch exchanges, none import legacy modules; the runtime contract is "caller supplies the snapshot, evaluator decides." That keeps them composable inside paper/shadow and replay paths while preserving the legacy semantic surface.

## Reason codes added (V2 risk taxonomy extension)

Defined as frozenset constants in `verdict.py`. Categorized:

ALLOW (one per gate):
- `allow_kill_switch_inactive`, `allow_halt_inactive`, `allow_latch_inactive`, `allow_close_guard_allow_close`, `allow_adl_inactive`, `allow_budget_within_limits`, `allow_margin_within_caps`, `allow_phase_within_ramp_limits`, `allow_toxicity_within_threshold`

CLOSE_ONLY (reduce-only / deleverage-required):
- `close_only_latch_active`
- `close_only_close_guard_emergency_bypass`
- `close_only_adl_account_cap_breach`, `close_only_adl_mu_cap_breach`, `close_only_adl_symbol_cap_breach`
- `close_only_margin_deleverage_required`

DENY (every gate has at least one fail-closed `_evidence_missing` path):
- kill_switch: `deny_kill_switch_active_global`, `deny_kill_switch_active_account`, `deny_kill_switch_active_symbol`, `deny_kill_switch_corrupt`, `deny_kill_switch_evidence_missing`
- halt: `deny_halt_active`, `deny_halt_fail_storm`, `deny_halt_mu_breach_sustained`, `deny_halt_evidence_missing`
- latch: `deny_latch_evidence_missing`
- close_guard: `deny_close_guard_defer_close`, `deny_close_guard_evidence_missing`
- adl: `deny_adl_evidence_missing`
- budget: `deny_budget_cadence_block`, `deny_budget_max_symbols_block`, `deny_budget_reversal_block`, `deny_budget_emergency_margin_block`, `deny_budget_evidence_missing`
- margin: `deny_margin_account_breach`, `deny_margin_symbol_breach`, `deny_margin_evidence_missing`
- phase: `deny_phase_max_mu_exceeded`, `deny_phase_min_free_margin_violated`, `deny_phase_max_positions_exceeded`, `deny_phase_per_symbol_margin_exceeded`, `deny_phase_equity_missing_or_nan`, `deny_phase_evidence_missing`
- toxicity: `deny_toxicity_extreme_block`, `deny_toxicity_evidence_missing`

These are additive. Claude's emitted namespace keeps the rich legacy-gate taxonomy in `services/risk_legacy_gates/verdict.py`. Codex remediation after the first review also extended the existing `v2/backend/app/domain/risk_gateway/record.py` reason constants with the nine shutdown-readiness gate reasons and added construction-level tests for those validator paths.

## Tests

Real, non-skipped tests added at `v2/backend/tests/unit/services/risk_legacy_gates/test_evaluators.py`. They import and invoke the real V2 callables. Coverage:

- 9 × "allow" path (one per gate)
- 9 × "deny" path (one per gate, non-evidence-missing reason where applicable)
- 9 × "deny evidence_missing" fail-closed path (one per gate)
- 6 × "close_only" path covering latch active, close-guard emergency bypass, ADL account/mu/symbol breach, margin deleverage
- 9 × `live_blocked == True` invariant per gate (asserted on returned verdict)
- Sanity test that every evaluator rejects `now_ms_clock` returning non-int / negative
- Sanity test that input dataclasses reject wrong types

Total: 40+ test assertions across the module.

Test execution evidence classification: V2_ENV_REQUIRED. Tests were drafted to run under the V2 lightweight venv. They are *not* run by this planner cycle (planner emits files only); execution is the harness's responsibility once materialized. If the harness reports failures, this task moves to BLOCKED with the failure log attached.

## Dependency closure

- Pure-Python; no new third-party deps.
- Imports only stdlib (`dataclasses`, `__future__`) inside the new modules.
- Does not import the legacy `risk/*` modules. Does not import legacy `config` shim. Does not import any v2 runtime worker. Stays composable.
- Does not modify any file under `v2/legacy_preserved/full_runtime_closure/risk/**`.
- Codex remediation modifies `v2/backend/app/domain/risk_gateway/record.py` to expose the nine legacy-gate reason constants needed by the existing `services.risk_gateway.*` adapter surface; construction-level validator tests now cover those constants.
- Does not modify `v2/backend/app/services/risk_gateway/service.py` or `v2/backend/app/composition/risk_gateway/runtime.py`.

## Public payload impact

None this cycle. The new evaluators are not yet wired into:
- the `v2_risk_gateway_runtime_worker` CLI worker public status payload
- the orchestrator decision → risk decision composition path
- any GUI surface

Therefore: `live_gate=blocked_human_only`, `live_symbols=[]`, `LEGACY_KILL_SWITCH_KEY_REFERENCES_AUDIT_ONLY` unchanged, public payload contract unchanged. A follow-on task (`claude_wire_v2_risk_gateway_legacy_gate_callables_into_decision_path`) is required before runtime impact.

## Legacy behavior mapping & remaining gaps

The exact legacy behavior is too broad for this cycle (≈6,671 lines across the 10 modules). What is implemented is the **minimal fail-closed paper/shadow parity surface**: a verdict-shaped projection of each gate's most safety-critical decision branches. The detailed branch-by-branch mapping and the explicit remaining-gap list are written to:

- `claude_port_v2_risk_gateway_legacy_gate_implementations_from_legacy_action_map_legacy_behavior_mapping.json`

High-level gap summary:

| Gate | Implemented | Remaining-gap (out of scope this cycle) |
|------|-------------|------------------------------------------|
| kill_switch | scope-aware active/inactive/corrupt deny | provenance capture, GLOBAL allowlist downgrade, TTL clamp, telegram dedupe |
| halt_manager | halted / fail_storm / mu_breach_sustained → deny | sustain-window state machine, telegram, phase-from-redis fallback |
| reduce_only_latch | latch_active vs risk_add → close_only / allow | per-symbol latch, latch TTL parse, expired-key cleanup |
| intelligent_close_guard | allow_close / defer_close / emergency_bypass | 2000+-feature hold_score, regime hash decode, msnap consult, per-tf consensus |
| auto_deleverager | account/mu/symbol cap breach → close_only | hedge-pair PAIR_REDUCE math, leg sizing, cadence, state-machine edge signals |
| shared_risk_gate | cadence / max_symbols / reversal / emergency_margin / OK | RBA Redis hgetall positions parse, protective-hedge cap mode, action_upper logging |
| margin_governor | ALLOW / BLOCK_account / BLOCK_symbol / DELEVERAGE | account-margin snapshot parse, symbol-cap math, hedge-add classification |
| phase_controller | max_mu / min_fmr / max_positions / per_sym / equity_nan | dynamic max-positions DD/vol/dq adjusters, phase override, ramp-from-redis |
| microstructure_toxicity | extreme-threshold deny / within-threshold allow | 7-component score recomputation, cache TTL, from_dict round-trip |

The remaining-gap list is materialized in the mapping JSON with one entry per gate so a follow-on can prioritize.

## GO / NO-GO

NO-GO for runtime wiring this cycle — by design. The artifacts add a real V2 surface that lets parity tests exist *now*, with `live_gate=blocked_human_only` preserved. Status flag: `BLOCKED_OR_REMEDIATED → REMEDIATED-MIN-SURFACE`.

Next required gates (not actioned here):
1. Codex review of the minimal parity surface vs. legacy modules.
2. Harness materialization + test execution log.
3. Wire callables into orchestrator-decision composition behind a dedicated `LEGACY_GATE_COMPOSITION_DEFER_HOLD` token, with non-skipped composition tests.
4. Reconcile the rich `risk_legacy_gates` verdict taxonomy with the coarser `RiskDecisionRecord` reason taxonomy if runtime composition needs one-to-one reason propagation.

## Evidence pointers

- Manifest: `claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/full_runtime_copied_source_manifest.json` — entries cited above.
- Baseline manifest: `claude_worklog/final_readiness/legacy_startup_baseline_v2_migration/latest/copied_baseline_manifest.json` — not directly cited because the gate modules live in the rl/risk/trainer/trader closure, not the startup baseline; this manifest is the canonical source for runtime entrypoints and is referenced in the broader closure audit, not here.
- Legacy sources: `v2/legacy_preserved/full_runtime_closure/risk/{kill_switch,halt_manager,reduce_only_latch,intelligent_close_guard,auto_deleverager,shared_risk_gate,margin_governor,phase_controller,microstructure_toxicity,adaptive_gate}.py`.
