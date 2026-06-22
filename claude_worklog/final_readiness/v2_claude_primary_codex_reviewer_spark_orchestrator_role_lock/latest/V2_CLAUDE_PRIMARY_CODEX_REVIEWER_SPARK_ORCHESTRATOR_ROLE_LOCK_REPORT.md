# V2 Claude-Primary, Codex-Reviewer, Spark-Orchestrator Role Lock

Generated: 2026-05-26T02:10:00Z
Git HEAD: 10513bbe0517fd81c9c87e4672bb15486a083c02
Lane: `v2_claude_primary_codex_reviewer_spark_orchestrator_role_lock`
GO/NO-GO: `V2_CLAUDE_PRIMARY_CODEX_REVIEWER_SPARK_ORCHESTRATOR_ROLE_LOCK_READY`
Upstream Codex gate: `V2_LEGACY_RUNTIME_FREEZE_PRIMARY_PAPER_CUTOVER_CODEX_PASS`

This packet installs the role-governance lock. Spark remains an
orchestrator/control-plane. Claude Code remains the primary implementation
executor. Codex remains the reviewer/approver and safe scoped fixer.
Spark must not be credited as implementation or review owner.

## Plain English

- **Executor:** Claude Code
- **Reviewer:** Codex
- **Orchestrator:** Spark
- **Runtime:** V2 primary paper/shadow
- **Live:** blocked

`live_gate=blocked_human_only`. `live_symbols=[]`.

## Required Policy

| Rule | Summary |
| --- | --- |
| 1. Implementation ownership | `owner=CLAUDE` for code/runtime implementation tasks; `agent=claude`. Spark may dispatch but not own. |
| 2. Review ownership | `owner=CODEX` for review tasks; `agent=codex`. Spark may enqueue but not own. |
| 3. Spark ownership scope | `owner=SPARK` only for orchestration/queue/lease/timer/metrics/report-center/infra-control. |
| 4. Lane registry enforcement | runtime/model/proof-claude execute; runtime/model/proof-codex review; spark-orchestration coordinates only. |
| 5. Descriptor validation | Reject Spark-owned implementation tasks, Spark-owned reviews, Spark mutating V2 runtime outside orchestration, Spark claiming Codex PASS/FAIL, Spark claiming Claude implementation completed. |
| 6. Report Center wording | Surface Executor=Claude Code, Reviewer=Codex, Orchestrator=Spark, Runtime=V2 primary paper/shadow, Live=blocked. |
| 7. Backward compatibility | Existing Spark wrappers, V2 timers, Claude/Codex worker services remain active. |

## Audit Results

881 task descriptors audited under `claude_worklog/agent_supervisor/tasks/*.json`:

| Field | Count |
| --- | --- |
| `owner=CLAUDE` | 100 |
| `owner=CODEX` | 96 |
| `owner=none_or_empty` (legacy, agent-authoritative) | 685 |
| **`owner=SPARK`** | **0** |
| `agent=codex` | 569 |
| `agent=claude` | 236 |
| `agent=ollama` | 5 |
| `agent=system_check` | 2 |
| `agent=none` | 69 |
| **`agent=spark`** | **0** |

Violations detected: **0**. Audit verdict: `ROLE_LOCK_INVARIANTS_CURRENTLY_HOLD`.

## Operational Role Counts (live evidence)

- Claude workers active: 3 (claude-1, claude-2, claude-3)
- Codex workers active: 3 (codex-1, codex-2, codex-3)
- Spark orchestration systemd timers active: 22

Worker process evidence:

- `v2_closed_loop_claude_worker --worker-id claude-1/2/3` (PIDs 1573506, 1572990, 1573127)
- `v2_closed_loop_codex_worker --worker-id codex-1/2/3` (PIDs 1573368, 1572936, 1573232)
- Spark orchestration: `v2_worker_porting_orchestrator daemon` (PID 430848); `ai-bot-v2-closed-loop-worker-pool.timer`, `ai-bot-v2-claude-task-runner.timer`, `ai-bot-v2-autonomous-mission-backlog.timer`, etc.

## Hard Prohibitions

- no V2 runtime stop
- no legacy restart
- no old Redis writes
- no exchange mutation
- no live/canary enable
- no approval tokens
- no Spark credited as implementation owner
- no Spark credited as reviewer
- no Spark emitting Codex PASS/FAIL
- no Spark emitting Claude implementation complete

## Backward Compatibility

- Existing Spark wrappers remain compatible
- All 22 V2 systemd timers remain active
- 3 Claude worker services remain active
- 3 Codex worker services remain active
- Zero workers/timers stopped, restarted, or replaced by this lane

## Required Outputs

- [GO_NO_GO.md](GO_NO_GO.md)
- [role_lock_policy.json](role_lock_policy.json) — 7 rules, 11 hard prohibitions, 3 role definitions
- [lane_owner_validation_status.json](lane_owner_validation_status.json) — 7 lane kinds, 13 sample lane assignments
- [task_descriptor_role_audit.json](task_descriptor_role_audit.json) — 881 tasks audited, 0 violations
- [report_center_role_surface_status.json](report_center_role_surface_status.json) — 12 surface contract fields
- [operator_dashboard_payload.json](operator_dashboard_payload.json)

## Verification

```text
python3 -c "import json,glob; [json.load(open(p)) for p in glob.glob('claude_worklog/final_readiness/v2_claude_primary_codex_reviewer_spark_orchestrator_role_lock/latest/*.json')]; print('OK')"

python3 -c "
import json, glob
spark_owner=0; spark_agent=0
for p in glob.glob('claude_worklog/agent_supervisor/tasks/*.json'):
    try: d=json.load(open(p))
    except: continue
    if (d.get('owner') or '').upper()=='SPARK': spark_owner+=1
    if (d.get('agent') or '').lower()=='spark': spark_agent+=1
assert spark_owner==0 and spark_agent==0
print('ROLE_LOCK_INVARIANTS_HOLD')
"
```
