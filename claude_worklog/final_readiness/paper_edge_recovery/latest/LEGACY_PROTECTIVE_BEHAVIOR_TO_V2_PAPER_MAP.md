# Legacy Protective Behavior To V2 Paper Map

Generated: `2026-05-15T05:39:50Z`

Pending equivalents are explicit blockers, not silent drops.

| Behavior | Legacy path | V2 paper status |
| --- | --- | --- |
| churn_prevention | legacy_reference/trading/churn_prevention.py | IMPLEMENTED_PARTIAL_FLIP_CHURN_ENTRY_GATE |
| lifecycle_controller | legacy_reference/trading/lifecycle_controller.py | EQUIV_PENDING_IMPLEMENTATION |
| exit_coordinator | legacy_reference/trading/exit_coordinator.py | EQUIV_PENDING_IMPLEMENTATION |
| dynamic_tp_engine | legacy_reference/trading/dynamic_tp_engine.py | EQUIV_PENDING_IMPLEMENTATION |
| dynamic_adaptive_stops | legacy_reference/trading/dynamic_adaptive_stops.py | EQUIV_PENDING_IMPLEMENTATION |
| stealth_stops | legacy_reference/trading/stealth_stops.py | BLOCKER_EQUIV_PENDING_IMPLEMENTATION |
| fee_ratio_gate | legacy_reference/trading/fee_ratio_gate.py | IMPLEMENTED_PARTIAL_COST_AWARE_ENTRY_GATE |
| adaptive_edge_gate | legacy_reference/trading/adaptive_edge_gate.py | IMPLEMENTED_PARTIAL_COST_AWARE_ENTRY_GATE |
| reduce_only_latch | legacy_reference/risk/reduce_only_latch.py | EQUIV_PENDING_IMPLEMENTATION |
| intelligent_close_guard | legacy_reference/risk/intelligent_close_guard.py | EQUIV_PENDING_IMPLEMENTATION |
| microstructure_toxicity | legacy_reference/risk/microstructure_toxicity.py | BLOCKER_EQUIV_PENDING_IMPLEMENTATION |
| risk_adaptive_gate | legacy_reference/risk/adaptive_gate.py | EXISTING_PARTIAL_RISK_GATE_PLUS_PAPER_EDGE_GATE |
| rl_churn_veto | legacy_reference/rl/churn_veto.py | IMPLEMENTED_PARTIAL_FLIP_CHURN_ENTRY_GATE |
| rl_minimum_hold_time | legacy_reference/rl/minimum_hold_time.py | EQUIV_PENDING_IMPLEMENTATION |
| rl_fee_ratio_reward_shaping | legacy_reference/rl/fee_ratio_reward_shaping.py | IMPLEMENTED_PARTIAL_COST_AWARE_ENTRY_GATE |
