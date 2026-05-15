# Legacy Protective Behavior To V2 Paper Map

Generated: `2026-05-15T10:57:30Z`

GO/NO-GO: `LEGACY_PROTECTIVE_BEHAVIOR_TO_V2_PAPER_MAP_READY_EDGE_PENDING`

This map does not approve live, canary, or legacy shutdown. V2 now has paper-only equivalents or explicit non-live exclusions for the mapped behaviors; positive edge and trainer parity remain unresolved.

| Behavior | Classification | Preserved legacy path | SHA256 | V2 paper evidence |
| --- | --- | --- | --- | --- |
| same_side_cooldown | IMPLEMENTED_IN_V2_PAPER | v2/legacy_preserved/full_runtime_closure/trading/churn_prevention.py | `f258b87233fc68d7d73e05f13fece322774bdf2a6e95ad8c081b83cbc3771d1f` | paper_online_runtime canary tightening emits same_symbol_same_direction_cooldown and paper_edge_scoring now fails closed when cooldown_clear is missing or false. |
| flip_cooldown | IMPLEMENTED_IN_V2_PAPER | v2/legacy_preserved/full_runtime_closure/trading/churn_prevention.py | `f258b87233fc68d7d73e05f13fece322774bdf2a6e95ad8c081b83cbc3771d1f` | paper_online_runtime canary tightening emits flip_churn_cooldown and paper_edge_scoring now fails closed when flip/churn evidence is missing or false. |
| churn_veto | IMPLEMENTED_IN_V2_PAPER | v2/legacy_preserved/full_runtime_closure/rl/churn_veto.py | `2c81e961b69c557dd684293cdcc6540fb7980ad42a404c5c8d08c24f9b241c74` | V2 blocks flip/churn candidates before paper fill; missing churn evidence now blocks by default. |
| fee_ratio_gate | IMPLEMENTED_IN_V2_PAPER | v2/legacy_preserved/full_runtime_closure/trading/fee_ratio_gate.py | `c1829afcbdb6848fb8dffd76e14b78a140832c663bb9c2f16e75029b0e7f8e7f` | V2 requires expected_move_after_cost_bps >= 8 after fee/spread/slippage/funding cost model. |
| adaptive_edge_gate | IMPLEMENTED_IN_V2_PAPER | v2/legacy_preserved/full_runtime_closure/trading/adaptive_edge_gate.py | `f50455f52e53eb5e2476cae4d2722d5050980cca66a6204c2f0ecf5526054632` | V2 cost-aware gate blocks missing/negative edge and keeps false-block evidence in shadow learning instead of loosening fills. |
| lifecycle_controller | IMPLEMENTED_IN_V2_PAPER | v2/legacy_preserved/full_runtime_closure/trading/lifecycle_controller.py | `cbe9472229be257701c2fc4d48f52ad6baab6a869947d55c8a8faf430d4fd6ed` | V2 paper lifecycle can open, hold, and close paper-only positions without exchange actions; positive edge remains unproven. |
| minimum_hold_time | IMPLEMENTED_IN_V2_PAPER | v2/legacy_preserved/full_runtime_closure/rl/minimum_hold_time.py | `6ab470cf50b756134ccb420f42831481d4edc5951f14f8fa2ae7bebcf68fc1ae` | V2 paper positions now carry minimum_hold_seconds=120 and TP/max-hold exits are suppressed while minimum_hold_active is true; stop-loss can still close defensively. |
| exit_coordinator | IMPLEMENTED_IN_V2_PAPER | v2/legacy_preserved/full_runtime_closure/trading/exit_coordinator.py | `fb0591c2a4ef29a40695556c536ef7998657135222dab86938a3ae4219941bc4` | V2 paper lifecycle now records paper_exit_coordinator_status and coordinates paper-only OPEN/HELD/CLOSED states with TP, stop, minimum-hold, and max-hold reasons without exchange actions. |
| dynamic_tp_simulation | IMPLEMENTED_IN_V2_PAPER | v2/legacy_preserved/full_runtime_closure/trading/dynamic_tp_engine.py | `54bf102e9d5cfedb00f22f953c4894c4592a1b627a16bad51c034a7069c1e908` | V2 paper lifecycle sets take_profit_bps from max(8, expected_move_after_cost_bps) and records dynamic_take_profit_model=expected_move_after_cost_bps_floor. |
| dynamic_stop_simulation | IMPLEMENTED_IN_V2_PAPER | v2/legacy_preserved/full_runtime_closure/trading/dynamic_adaptive_stops.py | `523ef574f6f6729c831047e73ce53bfad3d980cb562a386bf8b648b22d9d061f` | V2 paper lifecycle records dynamic_stop_model=paper_static_stop_floor_until_legacy_dynamic_stop_parity and enforces a defensive paper stop floor before non-defensive minimum-hold suppression. |
| stealth_stop_simulation | NOT_REQUIRED_FOR_PAPER_ONLY_WITH_REASON | v2/legacy_preserved/full_runtime_closure/trading/stealth_stops.py | `a76de1902e7c2a754f2e90a39fa9aac23d991ec059d5c54d6e0772b79b8a47cf` | Exchange-side stealth stop mutation is forbidden in V2 paper/shadow; paper lifecycle records simulated stops only. |
| reduce_only_protection | IMPLEMENTED_IN_V2_PAPER | v2/legacy_preserved/full_runtime_closure/risk/reduce_only_latch.py | `e0dc68486a5cc2fa0fc0ea1d1197f66373f8c090deb889a403257e187c7ac611` | paper_edge_scoring now requires reduce_only_clear/reduce_only_protection_clear evidence and fails closed with REDUCE_ONLY_PROTECTION_BLOCK when missing or false. |
| intelligent_close_guard | IMPLEMENTED_IN_V2_PAPER | v2/legacy_preserved/full_runtime_closure/risk/intelligent_close_guard.py | `7edf6d5eca3e8654bc17f0fad22831e4daedb411138d576904a29ab0a352c3ee` | paper_edge_scoring now requires intelligent_close_guard_clear/close_guard_clear evidence and paper lifecycle records paper_exit_coordinator_status for close coordination. |
| microstructure_toxicity | IMPLEMENTED_IN_V2_PAPER | v2/legacy_preserved/full_runtime_closure/risk/microstructure_toxicity.py | `5103e3078e15734eaca310e9ae58dd8e89725ebf4317a98313f078c8bd74beef` | feature snapshots expose microstructure_toxicity_score_bps from current volatility, paper_edge_scoring requires microstructure_toxicity_clear evidence, and high/missing toxicity blocks fills. |
| rl_fee_ratio_reward_shaping | NOT_REQUIRED_FOR_PAPER_ONLY_WITH_REASON | v2/legacy_preserved/full_runtime_closure/rl/fee_ratio_reward_shaping.py | `e7edce3e29a6bf7236329245ba4a14436dc6f6b0a249ad0ad3d05760570bfc06` | Reward shaping is trainer-learning behavior; V2 paper fill path uses runtime after-cost gate and shadow outcomes, not live reward mutation. |

## Summary

- behavior_count: `15`
- classification_counts: `{'IMPLEMENTED_IN_V2_PAPER': 13, 'NOT_REQUIRED_FOR_PAPER_ONLY_WITH_REASON': 2}`
- silently_dropped_behaviors: `[]`
- remaining_protective_behavior_gaps: `[]`

## Safety

- live_gate remains `blocked_human_only`.
- live_symbols remains `[]`.
- No old Redis writes, exchange actions, leverage changes, margin changes, approval tokens, or Redis trim approvals are introduced.
- Positive paper edge remains unproven.
- Trainer derived evidence still requires operator decision for paper-only shutdown evaluation.
