# Paste into Claude Code — Phase 1 (read-only system map)

You are now in Phase 1: complete read-only system cracking.

For this phase, do not build V2 yet.

Your only job is to understand the current trading bot from top to bottom.

You may read:
- ./legacy_reference/**
- ./audits/**
- ./requirements/**
- ./replay_data/**
- Redis read-only commands only
- filesystem logs if available

You may write only:
- ./claude_worklog/**

Do not modify old bot files.
Do not write to Redis.
Do not delete Redis keys.
Do not place orders.
Do not change leverage.
Do not change margin mode.
Do not run live trader.
Do not run live trainer.

Important:
Documentation in the repo is not trusted. Treat it as a claim. Validate every claim against code and runtime evidence.

Investigate the full system:
1. ingestors
2. market data collectors
3. feature pipeline
4. Redis feature keys
5. trainer models
6. trainer scripts
7. RL environment
8. orchestrator
9. signal generation
10. signal streams
11. risk assertions
12. halt manager
13. trader
14. execution wrappers
15. Binance/exchange client wrappers
16. stop-loss logic
17. take-profit logic
18. stealth stops
19. hedge logic
20. unwind logic
21. DCA/increase logic
22. leverage-adjust logic
23. margin-mode logic
24. execution feedback
25. executed_signals
26. PnL audit scripts
27. dashboards
28. configs and env usage
29. scripts started by cron/systemd/tmux/supervisor/docker
30. dependent scripts and wrappers
31. logs
32. all Redis streams/keys relevant to the bot

Create these files:
- ./claude_worklog/01_LEGACY_COMPONENT_MAP.md
- ./claude_worklog/02_LEGACY_DATA_FLOW.md
- ./claude_worklog/03_LEGACY_REDIS_MAP.md
- ./claude_worklog/04_LEGACY_CONFIG_MAP.md
- ./claude_worklog/05_LEGACY_EXECUTION_FLOW.md
- ./claude_worklog/06_LEGACY_RISK_FLOW.md
- ./claude_worklog/07_LEGACY_INGESTOR_FEATURE_FLOW.md
- ./claude_worklog/08_LEGACY_TRAINER_ORCHESTRATOR_FLOW.md
- ./claude_worklog/09_LEGACY_FAILURE_MODES.md
- ./claude_worklog/10_DOCS_VS_CODE_VALIDATION.md
- ./claude_worklog/11_RUNTIME_MONITOR_PLAN.md
- ./claude_worklog/12_V2_REQUIREMENTS_TRACEABILITY_MATRIX.md

For every component include:
- file paths
- class/function names
- inputs
- outputs
- Redis keys
- config variables
- scripts that start it
- external dependencies
- whether it can affect live trading
- known issues
- whether V2 should reuse, wrap, rewrite, or remove it

Also run only read-only Redis checks:
- XLEN on relevant streams
- XREVRANGE samples
- KEYS or SCAN for relevant namespaces
- HGETALL/GET only for relevant status keys

Do not use Redis write commands.

Final output of Phase 1:
1. complete old-system map
2. list of verified issues
3. list of unverified claims from docs
4. list of safety-critical gaps
5. list of V2 requirements derived from old-system failures
6. go/no-go decision for starting V2 build
