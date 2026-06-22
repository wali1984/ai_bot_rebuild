# V2 Liquidation WSS Daemon Governor Enrollment Report

GO/NO-GO: V2_LIQUIDATION_WSS_GOVERNOR_ENROLLMENT_READY

This packet does NOT approve real trading, canary trading, exchange
mutation, leverage/margin changes, legacy shutdown, Redis trim, or
paper-only shutdown acceptance. It does NOT modify legacy. It does
NOT pause the V2 runtime. It does NOT write old Redis keys. It does
NOT change daemon behavior; it only adds the daemon to the governor
expected-process checks.

## What changed

The continuous remediation review governor now treats the V2
liquidation WSS persistent paper/shadow daemon as a required V2
process. It also probes the daemon heartbeat key for freshness and
flags drift if the daemon stops writing v2-only or starts asserting
unsafe invariants.

### claude_worklog/tools/codex_continuous_remediation_review_governor.py

- REQUIRED_V2_PROCESSES grew from 12 to 13 entries. New entry:
  liquidation_wss_paper_shadow_daemon mapped to v2_liquidation_wss_loop.
- New module constants:
  - LIQUIDATION_WSS_HEARTBEAT_KEY = v2:market:liquidations:heartbeat
  - LIQUIDATION_WSS_HEARTBEAT_MAX_AGE_SECONDS = 180
- New liquidation_wss_heartbeat_probe() reads the heartbeat key,
  parses the payload, and returns presence, TTL, derived age, and
  the daemon self-reported safety invariants
  (process_mode, service_active, opt_in_enabled,
  no_synthetic_liquidation_events, writes_legacy_redis,
  writes_exchange_orders, gate, symbols).
- evaluate() now invokes the probe and adds five new fail blockers:
  - LIQUIDATION_WSS_HEARTBEAT_MISSING: key absent or empty payload.
  - LIQUIDATION_WSS_HEARTBEAT_TTL_NOT_POSITIVE: TTL <= 0.
  - LIQUIDATION_WSS_HEARTBEAT_STALE: age above 180s.
  - LIQUIDATION_WSS_DAEMON_WRITES_LEGACY_REDIS_DRIFT: payload asserts
    writes_legacy_redis = true.
  - LIQUIDATION_WSS_DAEMON_WRITES_EXCHANGE_ORDERS_DRIFT: payload
    asserts writes_exchange_orders = true.
  - LIQUIDATION_WSS_DAEMON_SYNTHETIC_EVENT_DRIFT: payload asserts
    no_synthetic_liquidation_events = false.
- The output summary block now exposes liquidation_wss_daemon so
  reviewers see daemon state at a glance.

### Helper scripts (unchanged in this packet)

The start, stop, and status helper scripts already include the WSS
daemon (UNITS and PATTERNS arrays) from the prior persistent-daemon
packet. No further edits were required:

- claude_worklog/tools/start_v2_production_replacement_runtime.sh
  already lists ai-bot-v2-liquidation-wss-paper-shadow.service.
- claude_worklog/tools/stop_v2_production_replacement_runtime.sh
  already lists the service in UNITS and the loop in PATTERNS.
- claude_worklog/tools/status_v2_production_replacement_runtime.sh
  already lists v2_liquidation_wss_loop in PATTERNS.

### Frontend truth payload (unchanged in this packet)

The frontend Monitor Center already reads the existing
v2_liquidation_wss_client status JSONs (3 cards added in the prior
persistent-daemon packet). No new frontend wiring was needed for the
governor enrollment.

## Governor run after the patch

The governor entrypoint was invoked once via its existing --once
mode (script path
claude_worklog/tools/codex_continuous_remediation_review_governor.py)
through the project venv. Output was written to
claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/continuous_remediation/codex_review/codex_5m_status.json
and the associated CODEX_GO_NO_GO.md.

Result snapshot read back from that status JSON:

- go_no_go = CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY
- fail_blockers = []
- v2_processes_running = 13 / 13 (was 12 / 12 before the patch)
- liquidation_wss_daemon snapshot:
  - present = true
  - ttl_seconds = 168 (positive)
  - heartbeat_age_seconds = 11 (well under the 180s threshold)
  - fresh = true
  - process_mode = persistent_daemon
  - service_active = true
  - opt_in_enabled = true
  - no_synthetic_liquidation_events = true
  - writes_legacy_redis = false
  - writes_exchange_orders = false

The expected process count increased by exactly one and the governor
remained READY with zero fail blockers.

## Required checks

- ai-bot-v2-liquidation-wss-paper-shadow.service active: PASS
  (systemctl --user is-active = active)
- v2_liquidation_wss_loop process running: PASS
  (governor process_status reports running=true for the new entry)
- v2:market:liquidations:heartbeat exists: PASS
- heartbeat TTL positive: PASS (168 at probe time)
- status payload fresh: PASS (heartbeat_age_seconds = 11)
- no synthetic per-symbol keys: PASS
  (redis scan v2:market:liquidations:latest:* = 0 keys;
   redis scan v2:market:liquidations:aggregate:* = 0 keys)
- no old Redis writes: PASS (governor source scan still green)
- no exchange mutation: PASS
- no approvals: PASS

## Safety invariants

- gate = blocked_human_only
- symbols = []
- approves_real = false
- approves_canary = false
- approves_legacy_shutdown = false
- approves_redis_trim = false
- writes_legacy_redis = false
- writes_exchange_orders = false
- no_synthetic_liquidation_events = true
- no_torch_imported = true
- no_pickle_loaded = true
- no_legacy_filesystem_modified = true

## What this packet does NOT do

- Does not approve real trading.
- Does not enable canary, legacy shutdown, Redis trim, or paper-only
  shutdown acceptance.
- Does not modify legacy.
- Does not change daemon behavior.
- Does not change daemon scheduling, retention, or write paths.
- Does not change cache TTL, per-symbol cooldown, or budget for any
  alternative-data provider.
- Does not place, modify, or cancel any exchange entry.
- Does not adjust leverage or margin.
- Does not create approval tokens.

## Outputs

- claude_worklog/final_readiness/v2_liquidation_wss_governor_enrollment/latest/GO_NO_GO.md
- claude_worklog/final_readiness/v2_liquidation_wss_governor_enrollment/latest/V2_LIQUIDATION_WSS_GOVERNOR_ENROLLMENT_REPORT.md
- claude_worklog/final_readiness/v2_liquidation_wss_governor_enrollment/latest/liquidation_wss_governor_enrollment_status.json
- v2/frontend/public/operator_runtime/v2_liquidation_wss_governor_enrollment/latest/operator_dashboard_payload.json
- claude_worklog/tools/codex_continuous_remediation_review_governor.py (modified)
