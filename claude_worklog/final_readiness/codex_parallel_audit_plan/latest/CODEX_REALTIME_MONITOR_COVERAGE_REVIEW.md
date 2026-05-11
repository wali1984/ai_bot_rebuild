# Codex Realtime Monitor Coverage Review

Generated: 2026-05-11

Scope: read-only review of realtime legacy monitoring continuity artifacts, Phase 3C runtime evidence, V2 dashboard payloads, and legacy monitor/control mutation paths. I did not modify `/home/wali/Desktop/AI BOT`, did not access or mutate Redis, did not place/cancel/modify exchange orders, did not change leverage/margin/position mode, and did not enable live execution.

## Verdict

Result: FAIL

Realtime monitoring continuity is backed by real Phase 3C artifact evidence, but it is not sufficient for online readiness coverage. The latest runtime snapshot is stale relative to the continuity generation time, the `READY` continuity label is easy to misread as live-readiness, the realtime continuity packet is not directly fetched by Mission Control, and hidden legacy control paths can indirectly start live/production trading or write Redis if invoked.

## Evidence Review

- Runtime evidence exists: Phase 3C dashboard evidence points to `claude_worklog/monitoring/snapshots.jsonl` and `claude_worklog/monitoring/trainer_metrics.jsonl`; both local files contain 11,755 lines. Phase 3C carries 200.95 observed hours, 11,755 snapshots, and 11,755 trainer metric records.
- The evidence is carried-forward artifact evidence, not current live runtime evidence. `current_runtime_sources.json` was generated at `2026-05-11T07:45:58.228145+00:00`, but the last snapshot is `2026-05-09T05:49:27.042047+00:00`.
- Freshness/source labels are partially truthful but not strong enough. The continuity bundle says source is `phase3c_runtime_monitor_verification` and lists snapshots/trainer metrics/runtime truth table, but names like `current_runtime_sources` and `REALTIME_LEGACY_MONITORING_CONTINUITY_READY` overstate freshness unless read as latest carried-forward artifacts.
- Phase 3C itself remains blocked: `CODEX_PHASE3C_GO_NO_GO.md` is `PHASE3C_12H_RUNTIME_MONITOR_CODEX_FAIL`, and the Phase 3C payload has `ready: false`.

## Visibility Review

- Redis memory pressure is visible in Phase 3C/Mission Control paths: max 99.51%, average 98.95%, latest ratio about 98.94%, threshold `critical_95`.
- Lineage gaps are visible in Phase 3C and continuity artifacts: execution lineage completeness is 0.0%, 400 executed rows have missing prediction IDs, 400 have missing feature snapshot IDs, and 400 have incomplete lineage tuples.
- The realtime continuity payload itself is not directly wired into `v2/frontend/src/pages/cockpitData.ts`; Mission Control fetches Phase 3C and Redis remediation payloads instead. That means the continuity-specific `ready_with_blocking_gaps` context is not first-class in the main operator surface.
- Operator Proof Dashboard does not surface current Redis memory pressure from the realtime/Phase 3C packets. It has lineage sections, but Redis pressure visibility depends on Mission Control/Phase 3C panels.
- Static/runtime labeling is uneven. Market feed freshness distinguishes `READONLY_MARKET_FEED` vs `STATIC_PROOF_FIXTURE`, but trainer/decision rows do not consistently render the same source/freshness mode.

## Mutation-Path Review

- No direct order, cancel, leverage, margin-mode, or position-mode mutation calls were found in targeted monitor/dashboard code scans.
- Hidden indirect live-start path exists: `/home/wali/Desktop/AI BOT/dashboard/api.py` exposes control endpoints that run scripts via `subprocess.Popen`; `POST /api/control/start_trading` launches `scripts/start_trader.sh`.
- `scripts/start_trader.sh` exports `AI_BOT_TRADING_MODE="PRODUCTION"` and launches `trading/trader.py --production --risk-management --portfolio-optimization`.
- `scripts/start_system.sh` can start Redis and invokes `start_trader.sh` in full/trading modes.
- Monitor-ish Redis write paths exist if those scripts are run: `services/service_monitor.py` writes `service_monitor:status` via `setex`; `rl/drift_monitor.py` writes `wma:drift_alerts`; `rl/position_monitor.py` writes `position_metadata:*` and expiry.

## Blocking Findings

- Runtime monitoring coverage is not current enough for online readiness: last runtime snapshot is about 50 hours older than the continuity artifact generation time.
- The continuity `READY` marker conflicts with underlying Phase 3C blocked/fail state unless explicitly scoped to continuity-only readiness.
- Main V2 dashboard coverage is incomplete: Redis pressure and lineage gaps are visible through adjacent Phase 3C/Redis panels, but the realtime continuity packet is not directly rendered.
- Hidden mutation/control paths remain in legacy dashboard/start scripts and would be unsafe if invoked from an operator UI or automation path.

## Required Result

CODEX_REALTIME_MONITOR_COVERAGE_FAIL
