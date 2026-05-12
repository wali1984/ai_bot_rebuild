# Automation Queue Refocus Report

Generated: 2026-05-12T21:28:13.241438+00:00

- Current queue next task: `LEGACY_TRAINER_RESTART_RUNTIME_CAPTURE_AND_V2_PARITY_SYNC_UNBLOCK`
- Lock-selected next task: `LEGACY_TRAINER_RESTART_RUNTIME_CAPTURE_AND_V2_PARITY_SYNC_UNBLOCK`
- Queue status age seconds: `25`
- Master planner status age seconds: `89579`
- Agent supervisor observed: `True`
- Scheduler observed: `True`
- Watchdog observed: `True`

The queue/status files still contain older recovery context. The lock does not hide that state; it supersedes it for next-task selection until the rebuild supervisor refreshes queue state.
