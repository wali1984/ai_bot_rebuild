SUPERVISOR_DASHBOARD_TRUTH_FIX

Current supervisor truth:
- Supervisor status files are stale/conflicting.
- Master planner process is not observed in the current read-only process scan.
- Autonomous governor process is not observed in the current read-only process scan.
- The dashboard must not hide this state.

UI fix:
- Mission Control first screen shows `SUPERVISOR_STATUS_STALE_OR_CONFLICTING`.
- Grouped nav shows a supervisor stale/conflicting operator status.
- Build Validation and other critical routes show route truth summaries before proof details.

Separate control-plane repair needed:
- If the project policy allows non-live supervisor recovery, create a separate supervised task to repair/restart the rebuild supervisor/daemon.
- Do not restart live trainer, live trader, live orchestrator, Redis, or VPN from this UI task.

Safety:
- No live execution state was changed.
- No Redis mutation occurred.
- Redis trim approval remains absent.
