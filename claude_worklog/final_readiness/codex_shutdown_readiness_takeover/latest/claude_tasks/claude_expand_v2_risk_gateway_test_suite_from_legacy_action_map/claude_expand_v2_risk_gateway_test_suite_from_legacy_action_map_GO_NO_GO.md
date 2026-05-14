CLAUDE_EXPAND_V2_RISK_GATEWAY_TEST_SUITE_FROM_LEGACY_ACTION_MAP_BLOCKED_OR_READY

Decision: **BLOCKED**
Classification: V2_ENV_BLOCKED / MISSING_EVIDENCE
Reason: V2 risk-gateway service exposes only `assemble_risk_decision_record`
over four orchestrator decision actions; none of the nine legacy gate
callables (kill_switch, halt_manager, reduce_only_latch,
intelligent_close_guard, auto_deleverager, shared_risk_gate,
margin_governor, phase_controller, adaptive_microstructure_toxicity)
have been ported into V2. Adding tests that import the read-only
`legacy_preserved` copies is forbidden; adding skipped tests is
forbidden; therefore no parity tests can be written this cycle.
Unblocker: port the nine gates and their reason codes to V2 first
(see REPORT §9), then re-dispatch this task.
Live gate: blocked_human_only.
Final approval token: absent.
