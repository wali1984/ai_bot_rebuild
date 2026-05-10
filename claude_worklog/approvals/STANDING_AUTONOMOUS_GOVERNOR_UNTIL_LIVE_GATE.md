# Standing Autonomous Governor Until Live Gate

The user delegates all non-live planning/build/review/remediation decisions to
the autonomous governor.

Allowed without further human prompts:
- V2 code/build/test/doc changes inside AI BOT REBUILD.
- Local package installs required for V2.
- Local non-live Docker/Postgres/Redis V2 services.
- Enterprise GUI development.
- Backend/API development.
- Local migrations/offline migrations.
- Script registry and system atlas.
- Monitor center.
- Trainer prediction monitor.
- Signal explainability.
- Risk gateway.
- Orchestrator adapter.
- Paper/shadow/replay.
- Read-only exchange market/account data.
- Legacy read-only importers.
- Local audit ledgers.
- Local evidence collectors.
- Claude/Codex/Ollama loops.
- Git commits and pushes.
- Codex review batches.
- Remediation of failed Codex reviews.
- Non-live data-plane maintenance when validation, backup, and Codex gates pass.

Still hard-stop human-only:
- Final live trading enablement.
- Real exchange order/cancel/close.
- Real leverage/margin/position-mode changes.
- Activation of live trading keys.
- Switching execution mode from paper/shadow to live.
- Disabling kill switch for live.
- Removing mandatory live safety gates.

Human approval packets for non-live matters are allowed, but they must not
block the whole queue. They must be converted into decision packets and the
planner must continue with the next safe task.

STANDING_AUTONOMOUS_GOVERNOR_UNTIL_LIVE_GATE
