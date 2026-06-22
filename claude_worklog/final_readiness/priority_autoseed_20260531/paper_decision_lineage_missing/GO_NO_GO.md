CLOSED_LOOP_TAKEOVER_CLAUDE_PRIORITY_PAPER_DECISION_LINEAGE_MISSING_20260531_CODEX_FAIL

Policy state for this review remains strict: `live_gate=blocked_human_only`, `live_symbols=[]`; do not approve live, canary, legacy shutdown, or Redis trim.

V2 review outcome: NO-GO. The requested lineage contract cannot be enforced without a prior contract amendment because runtime currently emits `orchestrator_decision_id` and lacks a first-class realtime `shadow_decision_id` path, while multiple V2 tests currently forbid both shadow lineage and canonical enforcement fields.
