# Requirements Inbox

This directory is the only place where new user requirements should be entered for autonomous rebuild processing.

The Claude Master Rebuild Planner must read this inbox every cycle.

Rules:
- Each requirement is one markdown file.
- Requirement files must not contain raw secrets.
- Requirement files may reference uploaded files, local paths, policies, or user decisions.
- Claude decides affected code/docs/tests/tasks.
- Codex reviews completed changes.
- Human is required only for live/legacy/Redis/exchange/deploy/secrets/L4/L5 gates.

REQUIREMENTS_INBOX_READY
