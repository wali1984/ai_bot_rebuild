CLAUDE_PORT_V2_RISK_GATEWAY_LEGACY_GATE_IMPLEMENTATIONS_FROM_LEGACY_ACTION_MAP_BLOCKED_OR_READY

Status: BLOCKED_OR_READY

Rationale: A minimal fail-closed paper/shadow parity surface for all nine gates has been added under `v2/backend/app/services/risk_legacy_gates/` with non-skipped unit tests. The surface is real and importable, but it is intentionally NOT wired into the orchestrator-decision composition, the risk-gateway runtime worker, or any public payload this cycle. `live_gate` remains `blocked_human_only`, `live_symbols=[]`, no exchange or old-Redis side effects, no final-approval token issued. Runtime wiring requires a follow-on task and Codex review.
