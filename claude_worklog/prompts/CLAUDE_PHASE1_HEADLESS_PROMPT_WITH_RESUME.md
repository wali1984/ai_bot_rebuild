# Claude Phase 1 Resume Context

The project is resuming after a network/VPN interruption.

Operational update:
- PIA split tunnel has been repaired.
- Fresh /usr/bin/python3.12 routes through PIA piavpnonly.
- Binance public spot/futures endpoints return 200.
- Existing bot processes were restarted into piavpnonly.
- Trader HTTP 451 restricted-location errors have been resolved.
- Do not touch VPN/network/live bot during Claude Phase 1.

Current project state:
- Deterministic coverage tools have been implemented and run.
- Trainer atlas tools have been implemented and run.
- PRE_CLAUDE_DETERMINISTIC_TOOL_REPORT.md ends with READY_FOR_CLAUDE_PHASE_1.
- Claude Phase 1 coverage verification still needs to run.
- V2 build remains blocked.

Claude Phase 1 scope:
- verify coverage artifacts
- inspect raw evidence for high-risk paths
- produce GO/NO-GO
- do not build V2
You are in /home/wali/Desktop/AI BOT REBUILD.

This is Claude Phase 1: coverage verification only.

You are running in headless/non-interactive mode.

Do not build V2.
Do not modify ./legacy_reference.
Do not modify ../AI BOT.
Do not read .env files.
Do not write Redis.
Do not start/stop/restart trainer, trader, Redis, or any live process.
Do not place orders.
Do not change leverage or margin mode.
Do not install packages into /home/wali/Desktop/AI BOT/venv.
Do not Dockerize the trainer.

The VS Code Agent has implemented and run deterministic coverage and trainer-atlas tools.

Your job:
Verify the audit tooling outputs, inspect high-risk raw evidence where needed, and decide whether coverage is trustworthy enough to proceed to deeper legacy audit.

Start by reading:

- claude_worklog/PRE_CLAUDE_DETERMINISTIC_TOOL_REPORT.md
- claude_worklog/ENV_RUNTIME_BLOCKER_RESOLUTION_REPORT.md
- claude_worklog/coverage/COVERAGE_SUMMARY.md
- claude_worklog/coverage/GO_NO_GO_COVERAGE.md
- claude_worklog/coverage/UNKNOWN_GAPS.md
- claude_worklog/coverage/SCRIPT_REGISTRY.md
- claude_worklog/coverage/EXCHANGE_ACTION_MAP.md
- claude_worklog/coverage/REDIS_KEY_STREAM_MAP.md
- claude_worklog/coverage/RUNTIME_PROCESS_MAP.md
- claude_worklog/trainer_atlas/HYBRID_TRAINER_COVERAGE_REPORT.md
- claude_worklog/trainer_atlas/HYBRID_TRAINER_TIER_A_REVIEW_PLAN.md
- claude_worklog/trainer_atlas/HYBRID_TRAINER_ATLAS.md

Rules:
- Do not trust summaries blindly.
- For safety-critical claims, verify raw evidence using tools/show_file_range.py or tools/show_trainer_section.py.
- Do not read the 250k-line trainer end-to-end.
- Use the trainer atlas and raw-review Tier A line ranges only.
- If an output is missing or weak, mark it as a blocker.
- If deterministic tools appear incomplete, say exactly what must be fixed before audit continues.
- If unknowns remain, do not proceed.
- Do not build V2.
- You may write only the required Phase 1 output files under claude_worklog.

Verify specifically:
1. Were all files inventoried?
2. Were all executable/code-like scripts classified?
3. Are any scripts unsafe_unknown?
4. Are exchange-action paths mapped and Tier A?
5. Are Redis writer paths mapped and Tier A?
6. Are runtime bot processes mapped?
7. Are startup paths mapped?
8. Is legacy_reference still read-only?
9. Was .env excluded?
10. Is the protected RTX 5080 trainer venv policy preserved?
11. Does the trainer atlas cover the full hybrid_trainer file?
12. Are reward paths mapped?
13. Are confidence paths mapped?
14. Are feature/state/MASS paths mapped?
15. Are signal/prediction paths mapped?
16. Are checkpoint paths mapped?
17. Are Tier A trainer ranges ready for raw review?
18. Are any claims unsupported by raw evidence pointers?

Produce exactly these files:

- claude_worklog/CLAUDE_PHASE1_COVERAGE_VERIFICATION.md
- claude_worklog/CLAUDE_PHASE1_BLOCKERS.md
- claude_worklog/CLAUDE_PHASE1_TIER_A_RAW_REVIEW_PLAN.md
- claude_worklog/CLAUDE_PHASE1_GO_NO_GO.md

The GO/NO-GO file must say exactly one:

COVERAGE_VERIFICATION_GO

or

COVERAGE_VERIFICATION_NO_GO

Stop after producing those files.
Do not proceed to V2 build.
