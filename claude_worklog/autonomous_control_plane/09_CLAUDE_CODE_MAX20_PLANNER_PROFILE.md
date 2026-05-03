# Claude Code Max 20x Planner Profile

## Objective

Use Claude Code Max 20x capacity to reduce excessive microtask splitting.

## Default mode

The master planner should generate consolidated milestone tasks by default.

Examples:
- one trainer-liveness implementation task instead of 060A/060B/060C
- one validation + Codex review handoff after implementation
- one remediation task per Codex FAIL, not several microtasks

## Fallback mode

Split tasks are still allowed when:
- Claude emits only partial output
- Claude emits wrong paths repeatedly
- output is too large
- quota/timeout occurs
- Codex asks for a narrow remediation
- validation requires isolating a failing component

## Required behavior

Planner must prefer:

consolidated_task -> validate -> Codex review -> remediation if needed

over:

microtask A -> microtask B -> microtask C -> manual stitching

## Rate-limit monitoring

Keep quota monitor active:
- check every 5 hours
- pause if blocked/limited
- do not loop on quota exhaustion

## Safety

Max 20x does not grant live authority.

Still forbidden:
- legacy bot mutation
- Redis writes/deletes
- live service restarts
- exchange actions
- live trading enablement
- deployment
- secret exposure

CLAUDE_CODE_MAX20_PLANNER_PROFILE_READY
