# Codex Governor Routing Update

Status: `CODEX_DESIGN_HANDOFF_REVIEW_PROTOCOL_READY`

## Behavior

When a folder exists under `claude_worklog/frontend_design/handoffs/`, the autonomous governor creates/selects a non-live L1 Codex parallel review task:

`codex_parallel_review_claude_design_handoff_enterprise_ui`

The task reviews the latest handoff, V2 frontend route/component/payload wiring, mock-data removal, placeholder rules, safety banners, TradingView replacement, monitor/trainer/config pages, and mutation boundaries.

## Non-Blocking Rule

Design review is a parallel audit lane. It must not block unrelated online-readiness tasks unless Codex finds a safety-critical live/Redis/exchange mutation path or a false live-status claim.

## Failure Handling

If Codex finds mock data, placeholder-only pages, missing live-block banner, unsafe controls, or evidence guessing, it marks the design implementation FAIL and creates a focused remediation task. The primary online-readiness lane continues unless the finding is safety-critical.

## Tool Coverage

- `claude_worklog/tools/autonomous_governor.py` creates the design-handoff Codex parallel review task when a handoff is present.
- `claude_worklog/tools/parallel_capacity_scheduler.py` already runs `codex_parallel_review_*.json` pending tasks, so the design review task uses that prefix.
- `claude_worklog/tools/codex_non_live_watchdog.py` remains the remediation/recovery lane for failed non-live Codex tasks and dirty/stale states.
