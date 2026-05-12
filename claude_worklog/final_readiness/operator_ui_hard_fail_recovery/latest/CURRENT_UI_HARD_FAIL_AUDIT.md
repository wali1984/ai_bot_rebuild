CURRENT_UI_HARD_FAIL_AUDIT

Status: confirmed and remediated in this pass.

Browser evidence captured before the fix showed `/admin/mission-control?role=admin` was routed correctly but still read like a proof/payload surface. The first screen exposed metric strips, text-heavy evidence cards, and raw payload-oriented panels before making the current operator truth obvious.

Root causes:
- Previous UI READY markers were not sufficient browser evidence.
- The Claude Design handoff was applied partly as shell/style treatment, while operator truth still rendered as tables and old cockpit cards.
- Payload freshness and proof fixtures were visually prominent enough to be mistaken for runtime truth.
- Supervisor stale/conflicting state and missing trainer runtime evidence were present, but not visually dominant.

Hard-fail evidence:
- `screenshots/before_mission_control.png`
- `screenshots/before_monitor_center.png`
- `screenshots/before_trainer_prediction.png`
- `screenshots/before_signal_explainability.png`

Required correction:
- Make the current runtime truth state the first operator surface.
- Preserve proof payloads, but label and lower-prioritize them.
- Keep live trading blocked and Redis trim deferred.
- Do not invent trainer/runtime evidence.
