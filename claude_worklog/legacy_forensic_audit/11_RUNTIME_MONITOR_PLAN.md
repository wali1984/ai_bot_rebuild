# 11 Runtime Monitor Plan (Read-Only)

## Summary
Proposed read-only runtime monitor plan duration: **12 hours**.
Sampling interval: **60 seconds** baseline + **5 minutes** rollup.

## Monitor targets
- Redis keys/streams (read-only): signal streams, position namespaces, portfolio snapshots, trainer/trader heartbeats.
- Logs: trainer, orchestrator, trader, ingestors.
- Processes: mapped runtime services from `RUNTIME_PROCESS_MAP.json`.
- Trainer metrics: prediction cadence, confidence distributions, skip reasons.
- Trader metrics: execution decisions, protective actions, duplicate suppression.
- Signal attribution: signal_id/decision_id lineage completeness.
- Exchange errors: API failure class and retry behavior.
- Memory pressure: process RSS growth, worker fan-out pressure indicators.
- VPN/routing state: process/route state observation only (no network mutation).

## Expected outputs
- hourly health snapshots
- anomaly timeline
- unresolved risk deltas
- recommendation for next forensic step

## Raw evidence pointers
- claude_worklog/coverage/TIER_A_RAW_REVIEW_PLAN.json
- claude_worklog/coverage/EXCHANGE_ACTION_MAP.json
- claude_worklog/coverage/REDIS_USAGE_MAP.json
- claude_worklog/trainer_atlas/HYBRID_TRAINER_COVERAGE_REPORT.md

## Source artifacts used
- claude_worklog/coverage/FILE_MANIFEST.json
- claude_worklog/coverage/SCRIPT_REGISTRY.json
- claude_worklog/coverage/SCRIPT_DEPENDENCY_GRAPH.json
- claude_worklog/coverage/STARTUP_PATH_MAP.json
- claude_worklog/coverage/RUNTIME_PROCESS_MAP.json
- claude_worklog/coverage/REDIS_USAGE_MAP.json
- claude_worklog/coverage/EXCHANGE_ACTION_MAP.json
- claude_worklog/coverage/CONFIG_ENV_MAP.json

## Verification commands
- python3 tools/show_file_range.py --file "./legacy_reference/rl/hybrid_trainer.py" --start 1 --end 80
- python3 tools/show_trainer_section.py --trainer-file ./legacy_reference/rl/hybrid_trainer.py --start 30000 --end 30120
- python3 tools/codex_adversarial_coverage_check.py

## Unresolved questions
- Which Tier A unresolved items need code-owner adjudication before production deprecation mapping?
- Which legacy scripts are wrappers only and can be archived in V2 migration phase?

## Confidence level
- Medium-High
