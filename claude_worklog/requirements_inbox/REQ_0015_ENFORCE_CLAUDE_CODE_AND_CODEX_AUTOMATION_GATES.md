# Requirement 0015 — Enforce Claude Code and Codex Automation Gates

## Objective

Move automation safety and recovery rules from prompt instructions into deterministic project controls.

## Required controls

1. Claude Code hook-style preflight checks
   - block writes outside AI BOT REBUILD
   - block `/home/wali/Desktop/AI BOT`
   - block Redis writes/deletes
   - block live service restarts
   - block exchange/order/leverage/margin actions
   - block deployment and live trading enablement
   - block secret exposure

2. Supervisor pre-dispatch gates
   - validate task risk level
   - validate cwd
   - validate allowed output prefixes
   - validate no active child conflict
   - validate git state
   - validate standing non-live approval
   - skip superseded evidence tasks

3. Codex watchdog lane
   - run automatically when:
     - human_attention_required appears
     - planner emits no-progress/halt loop
     - git dirty with no active process
     - materialization path mismatch occurs
     - Codex FAIL marker appears
     - stale status conflicts with PASS evidence
   - produce diagnostic report
   - if safe, autofix
   - validate, secret-scan, commit/push, re-review

4. Evidence-first reconciliation
   - GO/NO-GO PASS markers override stale queue/current_status noise
   - stale tasks become superseded_by_evidence
   - stale tasks must not execute

5. Rate-limit enforcement
   - quota guard checks every 5 hours
   - if Claude Code limited, pause planner
   - Codex can continue read-only diagnostics/reviews during Claude cooldown

6. Dashboard enforcement visibility
   - show Claude profile
   - show Codex watchdog active/inactive
   - show active requirement
   - show active task
   - show latest evidence marker
   - show stale/superseded states
   - show live gate blocked

## Codex authority

Codex has full authority to fix non-live human_attention_required blockers inside AI BOT REBUILD.

Codex may modify:
- v2/
- claude_worklog/tools/
- claude_worklog/agent_supervisor/
- claude_worklog/phase2_core_rebuild/
- claude_worklog/security/
- claude_worklog/requirements_inbox/
- claude_worklog/autonomous_control_plane/
- claude_worklog/agent_supervisor_reliability/

Codex may not:
- modify /home/wali/Desktop/AI BOT
- write/delete Redis keys
- restart live services
- place/cancel orders
- change leverage/margin
- enable live trading
- deploy
- run production migrations
- expose or commit secrets
- approve final live gate

REQ_ENFORCE_CLAUDE_CODE_AND_CODEX_AUTOMATION_GATES_READY
