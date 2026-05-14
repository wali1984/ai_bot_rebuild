# Legacy Baseline Analysis — Nine Risk Gates for V2 Parity Test Expansion

Date: 2026-05-14
Source manifest: `claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/full_runtime_copied_source_manifest.json`
Startup baseline manifest: `claude_worklog/final_readiness/legacy_startup_baseline_v2_migration/latest/copied_baseline_manifest.json`
Legacy action path map: `claude_worklog/final_readiness/legacy_rl_risk_trainer_trader_closure/latest/trader_risk_action_path_map.json`
All legacy gate files have manifest `status: UNCHANGED`, `safe_to_commit: true`.

## 1. kill_switch

- Legacy path: `risk/kill_switch.py`
- V2 preserved path: `v2/legacy_preserved/full_runtime_closure/risk/kill_switch.py`
- SHA256: `bf730c6fa425097aa0c246dfbab88e4f8d158afdd606a905c8f9e3c7695df59e`
- Size: 6143 bytes
- Legacy responsibility: global per-symbol/per-account kill flag that
  forces deny-everything when active. Listed in
  `trader_risk_action_path_map.json:risk_gate_files`.
- Required V2 parity test (from action map):
  `kill_switch_active_denies_everything`
- Required V2 callable: `services.risk_gateway.kill_switch.evaluate_kill_switch_state(...)` — **ABSENT**
- Required V2 reason code: `deny_kill_switch_active` — **ABSENT**
- Test outcome contract: when kill-switch active → `risk_action=deny`
  for both `open_long` and `open_short` inputs.

## 2. halt_manager

- Legacy path: `risk/halt_manager.py`
- V2 preserved path: `v2/legacy_preserved/full_runtime_closure/risk/halt_manager.py`
- SHA256: `49504d73a9fef319eb0ac6282d571492714a62526bc1c9849148685ad7eac314`
- Size: 22707 bytes
- Legacy responsibility: time-bounded halt windows (manual, drawdown,
  event-driven). Listed in `risk_gate_files`.
- Required V2 parity test: `halt_manager_active_denies_everything`
- Required V2 callable: `services.risk_gateway.halt_manager.evaluate_halt_state(...)` — **ABSENT**
- Required V2 reason code: `deny_halt_manager_active` — **ABSENT**

## 3. reduce_only_latch

- Legacy path: `risk/reduce_only_latch.py`
- V2 preserved path: `v2/legacy_preserved/full_runtime_closure/risk/reduce_only_latch.py`
- SHA256: `e0dc68486a5cc2fa0fc0ea1d1197f66373f8c090deb889a403257e187c7ac611`
- Size: 5935 bytes
- Legacy responsibility: once latched, denies any position-increasing
  intent (open in same direction or flip increasing size).
- Required V2 parity test: `reduce_only_latch_denies_increase_position`
- Required V2 callable: `services.risk_gateway.reduce_only_latch.evaluate_latch_state(...)` — **ABSENT**
- Required V2 reason code: `deny_reduce_only_latch` — **ABSENT**

## 4. intelligent_close_guard

- Legacy path: `risk/intelligent_close_guard.py`
- V2 preserved path: `v2/legacy_preserved/full_runtime_closure/risk/intelligent_close_guard.py`
- SHA256: `7edf6d5eca3e8654bc17f0fad22831e4daedb411138d576904a29ab0a352c3ee`
- Size: 47000 bytes
- Legacy responsibility: forces close-only mode while a safety
  predicate holds (e.g., dangerous volatility, broken feeds), but
  selectively allows closing actions to drain risk.
- Required V2 parity test: `intelligent_close_guard_overrides_close_only_if_safety_holds`
- Required V2 callable: `services.risk_gateway.intelligent_close_guard.evaluate_close_guard(...)` — **ABSENT**
- Required V2 reason code: `allow_close_only_intelligent_close_guard` — **ABSENT**

## 5. auto_deleverager

- Legacy path: `risk/auto_deleverager.py`
- V2 preserved path: `v2/legacy_preserved/full_runtime_closure/risk/auto_deleverager.py`
- SHA256: `76652e99ec0b0717a3bfea887c25f78746df7765ba3f5e4eff6a21d0e820a377`
- Size: 85148 bytes
- Legacy responsibility: triggers reduce-only mode for a symbol when
  ADL-style thresholds trip (drawdown, leverage, equity slope).
- Required V2 parity test: `auto_deleverager_triggered_position_reduce_only`
- Required V2 callable: `services.risk_gateway.auto_deleverager.evaluate_adl_state(...)` — **ABSENT**
- Required V2 reason code: `deny_auto_deleverager_triggered` — **ABSENT**

## 6. shared_risk_gate / risk_budget_allocator (shared risk budget)

- Legacy path A: `risk/shared_risk_gate.py`
- V2 preserved path A: `v2/legacy_preserved/full_runtime_closure/risk/shared_risk_gate.py`
- SHA256 A: `62c2403f2cf2ce5dec71522b919f1db6a2f6908e338903e359e021c75c59dd7f`
- Size A: 18022 bytes
- Legacy path B: `risk/risk_budget_allocator.py`
- V2 preserved path B: `v2/legacy_preserved/full_runtime_closure/risk/risk_budget_allocator.py`
- SHA256 B: `e0a178d139695f97541e67f00ecaf7d8e7b7928e0290ba6a54edc0cfcfb1e832`
- Size B: 22010 bytes
- Legacy responsibility: enforces global/category risk budget by
  denying new exposure when allocator marks the budget exhausted.
- Required V2 parity test: `shared_risk_gate_denies_when_budget_exhausted`
- Required V2 callable: `services.risk_gateway.shared_risk_gate.evaluate_budget_state(...)` — **ABSENT**
- Required V2 reason code: `deny_shared_risk_budget_exhausted` — **ABSENT**

## 7. margin_governor

- Legacy path: `risk/margin_governor.py`
- V2 preserved path: `v2/legacy_preserved/full_runtime_closure/risk/margin_governor.py`
- SHA256: `e8448d2ee70697a97fbb4af27555adabe2af590d8185ebfc644b965070376eee`
- Size: 38468 bytes
- Legacy responsibility: blocks leverage-increasing actions and
  enforces margin-mode invariants.
- Required V2 parity test: `margin_governor_denies_leverage_increase`
- Required V2 callable: `services.risk_gateway.margin_governor.evaluate_margin_state(...)` — **ABSENT**
- Required V2 reason code: `deny_margin_governor_leverage_increase_blocked` — **ABSENT**

## 8. phase_controller

- Legacy path: `risk/phase_controller.py`
- V2 preserved path: `v2/legacy_preserved/full_runtime_closure/risk/phase_controller.py`
- SHA256: `ecd566ca7537551a9e6e267da4880a41764d346a1d43137d4088003951211ee1`
- Size: 13441 bytes
- Legacy responsibility: gates trading by lifecycle phase
  (warmup / probation / steady / cooldown).
- Required V2 parity test: `phase_controller_blocks_in_warmup_phase`
- Required V2 callable: `services.risk_gateway.phase_controller.evaluate_phase_gate(...)` — **ABSENT**
- Required V2 reason code: `deny_phase_controller_warmup` — **ABSENT**

## 9. adaptive_microstructure_toxicity (adaptive_gate + microstructure_toxicity)

- Legacy path A: `risk/microstructure_toxicity.py`
- V2 preserved path A: `v2/legacy_preserved/full_runtime_closure/risk/microstructure_toxicity.py`
- SHA256 A: `5103e3078e15734eaca310e9ae58dd8e89725ebf4317a98313f078c8bd74beef`
- Size A: 10715 bytes
- Legacy path B: `risk/adaptive_gate.py` (consumer of toxicity score; preserved alongside)
- Legacy responsibility: blocks entries when microstructure toxicity
  metric exceeds adaptive threshold.
- Required V2 parity test: `adaptive_gate_blocks_on_microstructure_toxicity`
- Required V2 callable: `services.risk_gateway.adaptive_gate.evaluate_toxicity_block(...)` — **ABSENT**
- Required V2 reason code: `deny_adaptive_microstructure_toxic` — **ABSENT**

## 10. V2 current surface (raw evidence)

- `v2/backend/app/services/risk_gateway/service.py` exposes only
  `assemble_risk_decision_record`; branches on four
  `decision.decision_action` values; emits four risk reason codes;
  forces `live_blocked=True`.
- `v2/backend/app/domain/risk_gateway/record.py` allowlists exactly
  five risk reason codes: `allow_proceed_long`, `allow_proceed_short`,
  `deny_orchestrator_held`, `deny_orchestrator_abstained`, `deny_default`.
- No service files exist for any of the nine legacy gates inside
  `v2/backend/app/services/risk_gateway/` (directory contents:
  `__init__.py`, `errors.py`, `service.py`).
- No domain reason-code constants exist for any of the nine gates.
- Verification commands:
  - `ls v2/backend/app/services/risk_gateway/`
  - `ls v2/backend/app/domain/risk_gateway/`
  - `grep -n "deny_kill_switch_active\|deny_halt_manager_active\|deny_reduce_only_latch\|deny_auto_deleverager_triggered\|deny_shared_risk_budget_exhausted\|deny_margin_governor_leverage_increase_blocked\|deny_phase_controller_warmup\|deny_adaptive_microstructure_toxic\|allow_close_only_intelligent_close_guard" v2/backend/app/domain/risk_gateway/record.py`
    → expected: no matches (confirms domain reason codes absent).
- Confidence: HIGH on absence of callables and reason codes; HIGH on
  presence of legacy preserved copies with SHA256 matches.
- Missing evidence: none required for the BLOCKED classification —
  absence of V2 callables is positively verified via filesystem listing.

## 11. Trader/baseline cross-reference

The startup-baseline copy (`copied_baseline_manifest.json`, totals
`required: 39, copied: 33, missing: 6`) contains no `risk/*` files —
it covers ingest, scripts, and feature pipeline only — so none of the
nine gate SHAs are repeated there. The authoritative SHA citations
for the nine gates come exclusively from
`full_runtime_copied_source_manifest.json`.

## 12. Conclusion

All nine legacy gates have closed, SHA-cited preserved copies, and the
legacy action-path map records the exact parity-test names required.
The blocker is exclusively on the V2 side: no callable V2 gate
functions and no domain reason codes exist for any of the nine gates.
Until they are ported, the parity-test expansion cannot honour the
"invoke real V2 gate functions and must not skip" constraint.

Status: **BLOCKED_OR_REMEDIATED — V2_ENV_BLOCKED / MISSING_EVIDENCE**.
