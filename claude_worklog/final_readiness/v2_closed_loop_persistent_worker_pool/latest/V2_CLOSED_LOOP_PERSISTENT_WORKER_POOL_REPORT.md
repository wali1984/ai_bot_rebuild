# V2 Closed-Loop Persistent Worker Pool Report

Marker: `V2_CLOSED_LOOP_PERSISTENT_WORKER_POOL_READY`
Generated: 2026-05-25T01:15:52Z

## Worker Pool Utilization

| metric | value |
| --- | --- |
| worker_count_total | 6 |
| worker_count_active | 6 |
| worker_count_busy | 3 |
| worker_count_idle_ready | 2 |
| active_lane_count | 6 |
| active_claude_workers | 3 |
| active_codex_workers | 3 |
| current_automatable_count | 7 |
| active_lane_shortfall_reason | None |
| blocker | None |

## Workers (fresh heartbeat only)

| worker_id | lane_type | pid | state | current_task_id | last_heartbeat |
| --- | --- | --- | --- | --- | --- |
| claude-1 | CLAUDE_IMPLEMENTATION | 1573506 | busy | closed_loop_remediation_codex_review_autoseed_paper_edge_false_negative_gate_reason_enrichment_r16 | 2026-05-25T01:15:49Z |
| claude-2 | CLAUDE_IMPLEMENTATION | 1572990 | busy | claude_autoseed_paper_fill_gate_block_reason_recording_r2 | 2026-05-25T01:15:43Z |
| claude-3 | CLAUDE_IMPLEMENTATION | 1573127 | busy | claude_v2_runtime_soak_and_production_equivalence_remediation | 2026-05-25T01:15:46Z |
| codex-1 | CODEX_REVIEW | 1573368 | idle_ready | None | 2026-05-25T01:15:47Z |
| codex-2 | CODEX_REVIEW | 1572936 | claiming | None | 2026-05-25T01:15:52Z |
| codex-3 | CODEX_REVIEW | 1573232 | idle_ready | None | 2026-05-25T01:15:44Z |

## Current Task Assignments

| worker_id | task_id | lane_type | file_lock_group | leased_at |
| --- | --- | --- | --- | --- |
| claude-3 | claude_v2_runtime_soak_and_production_equivalence_remediation | REMEDIATION | claude_v2_runtime_soak_and_production_equivalence_remediation | 2026-05-25T01:10:16Z |
| claude-1 | closed_loop_remediation_codex_review_autoseed_paper_edge_false_negative_gate_reason_enrichment_r16 | REMEDIATION | v2_paper_edge_false_negative_gate_reason_enrichment | 2026-05-25T01:11:04Z |
| claude-2 | claude_autoseed_paper_fill_gate_block_reason_recording_r2 | CLAUDE_IMPLEMENTATION | v2_paper_fill_gate_block_reason_recording | 2026-05-25T01:13:43Z |

## Blockers

- (none)

## Safety

- live_gate=blocked_human_only
- live_symbols=[]
- approves_live=false
- approves_canary=false
- approves_legacy_shutdown=false
- approves_redis_trim=false
