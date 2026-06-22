# Codex Review: V2 Liquidation WSS Persistent Paper/Shadow Daemon

Generated: `2026-05-18T01:44:20Z`

GO/NO-GO: `V2_LIQUIDATION_WSS_PERSISTENT_DAEMON_CODEX_FAIL`

## Decision

Codex fails the daemon-level review. The systemd service is active and running the expected bounded V2 paper/shadow WSS command with opt-in enabled, but the required heartbeat key is not fresh and is currently absent from Redis.

Do not add this daemon to fail-blocking governor requirements until the heartbeat freshness issue is fixed and re-reviewed.

This review does not approve live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, external feed adoption, paid endpoints, or legacy shutdown.

## Systemd And Process Evidence

- Service: `ai-bot-v2-liquidation-wss-paper-shadow.service`
- `systemctl --user is-active`: `active`
- `ActiveState`: `active`
- `SubState`: `running`
- `MainPID`: `3465777`
- Process command:
  - `python3 -m v2.backend.app.cli.v2_liquidation_wss_loop`
  - `--total-seconds 86400`
  - `--max-seconds-per-session 600`
  - `--max-events-per-session 1000`
- Restart policy:
  - `Restart=always`
  - `RestartSec=15`
- Unit output paths:
  - `claude_worklog/agent_supervisor/logs/control_plane/v2_liquidation_wss_loop.log`
  - `claude_worklog/agent_supervisor/logs/control_plane/v2_liquidation_wss_loop.err`

The live process environment includes:

- `V2_LIQUIDATION_WSS_OPT_IN=true`
- `LIVE_GATE=blocked_human_only`

Note: live process `PYTHONPATH` is parsed as `/home/wali/Desktop/AI`, because the unit's `Environment=PYTHONPATH=/home/wali/Desktop/AI BOT REBUILD` is not quoted. The process is still running from the correct working directory, but the unit should be corrected in the next remediation.

## Fail Blockers

- `LIQUIDATION_WSS_HEARTBEAT_NOT_FRESH`
  - `redis-cli TTL v2:market:liquidations:heartbeat` returned `-2`.
  - `redis-cli GET v2:market:liquidations:heartbeat` returned no payload.
  - Required heartbeat freshness is therefore not proven.
- `STATUS_PAYLOAD_NOT_DAEMON_FRESH`
  - Public/worklog WSS status payloads are not being refreshed by the persistent daemon while it runs.
  - The observed status files were older than the current review and did not expose current daemon session fields.
- `HEARTBEAT_TTL_SHORTER_THAN_SESSION_BOUNDARY`
  - Source writes the heartbeat at session end.
  - Service uses `--max-seconds-per-session 600`.
  - `write_heartbeat` uses TTL `300`.
  - A quiet market window can therefore let the heartbeat expire before the next session-end write.

These blockers are runtime-liveness blockers only. They are not live/shutdown approvals and do not imply exchange mutation.

## Redis State

Observed Redis keys:

- `v2:market:liquidations:heartbeat`: absent
- `v2:market:liquidations:latest:*`: none
- `v2:market:liquidations:aggregate:*`: none
- `v2:market:liquidations:*`: none

The absence of per-symbol latest/aggregate keys is acceptable if no `forceOrder` events occurred. It is not acceptable for the heartbeat key to be absent.

## Source Safety

Reviewed:

- `v2/backend/app/cli/v2_liquidation_wss_loop.py`
- `v2/backend/app/services/native_ingestors/liquidations_wss.py`
- `claude_worklog/systemd/user/ai-bot-v2-liquidation-wss-paper-shadow.service`

Codex verified:

- WSS opt-in is required by `V2_LIQUIDATION_WSS_OPT_IN=true`.
- Redis write functions use V2 liquidation key templates.
- No synthetic liquidation events are created in source.
- No exchange order placement/cancel/modify calls were found.
- Safety payload fields keep:
  - `live_gate=blocked_human_only`
  - `live_symbols=[]`
  - `approves_live=false`
  - `approves_canary=false`
  - `approves_legacy_shutdown=false`
  - `approves_redis_trim=false`

## Runtime Continuity

Existing runtime/remediation state remains healthy:

- Continuous remediation governor: `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`
- V2/remediation processes: `12/12`
- 6h soak remains passed.
- V2 Redis namespaces remain non-empty.
- Full observation builder payload remains fresh.
- No fail blockers were emitted by the continuous remediation governor.

Full observation builder remains partial:

- state: `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`
- target dim: `1911`
- generated dims: `BTCUSDT=148`, `ETHUSDT=148`, `SOLUSDT=143`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`

## Validation

- Focused WSS tests: `18 passed`.
- Daemon process active check: PASS.
- Bounded command flags check: PASS.
- Opt-in/live-gate env check: PASS.
- Per-symbol key non-fabrication check: PASS, no latest/aggregate keys found.
- Heartbeat freshness check: FAIL.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.

## Required Remediation

Fix heartbeat/status freshness without touching legacy or enabling live. Acceptable remediation examples:

- emit heartbeat at process start and on an interval shorter than TTL during long quiet sessions; or
- set heartbeat TTL longer than the maximum session duration; and
- refresh public/worklog status on the same cadence.

Then rerun this Codex daemon review before adding the daemon to fail-blocking governor requirements.

## Safety State

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`

## Final Decision

`V2_LIQUIDATION_WSS_PERSISTENT_DAEMON_CODEX_FAIL`
