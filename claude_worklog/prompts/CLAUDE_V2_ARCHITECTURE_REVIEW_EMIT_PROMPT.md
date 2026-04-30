You are Claude Code operating locally in /home/wali/Desktop/AI BOT REBUILD.

Task:
Perform a strict architecture review of the completed V2 enterprise architecture package.

Rules:
- Do not modify /home/wali/Desktop/AI BOT.
- Do not modify legacy_reference.
- Do not read .env files.
- Do not write Redis.
- Do not restart services.
- Do not build V2 code.
- Do not install packages.
- Do not touch live bot.

Review inputs:
- claude_worklog/v2_architecture/*.md
- claude_worklog/v2_requirements/*.md
- claude_worklog/post_monitor/*.md
- claude_worklog/continuous_monitoring/*.md
- claude_worklog/continuous_monitoring_impl/*.md
- claude_worklog/legacy_forensic_audit/*.md
- claude_worklog/codex/CODEX_ADVERSARIAL_COVERAGE_REVIEW.md
- claude_worklog/CLAUDE_PHASE1_GO_NO_GO.md

Context:
The V2 platform must be an enterprise website-first AI trading platform, not a basic dashboard. It must include passive all-market discovery, adaptive symbol selection, dynamic hot-reload, multi-exchange futures connectors, multi-trader fleet, full feature-to-action explainability, continuous Claude/Codex/Ollama supervision, AI action governance, public-hosting security, mobile/iPhone readiness, hard risk gateway, and live trading blocked by default.

You are running in headless/non-interactive mode. Do NOT try to write files using tools. Instead, PRINT the full content for each required file in this exact envelope format:

BEGIN_FILE: claude_worklog/v2_architecture_review/01_ARCHITECTURE_COMPLETENESS_REVIEW.md
<full file content>
END_FILE

BEGIN_FILE: claude_worklog/v2_architecture_review/02_REQUIREMENTS_TRACEABILITY_REVIEW.md
<full file content>
END_FILE

BEGIN_FILE: claude_worklog/v2_architecture_review/03_ENTERPRISE_GUI_REVIEW.md
<full file content>
END_FILE

BEGIN_FILE: claude_worklog/v2_architecture_review/04_DYNAMIC_UNIVERSE_AND_HOT_RELOAD_REVIEW.md
<full file content>
END_FILE

BEGIN_FILE: claude_worklog/v2_architecture_review/05_MULTI_EXCHANGE_AND_MULTI_TRADER_REVIEW.md
<full file content>
END_FILE

BEGIN_FILE: claude_worklog/v2_architecture_review/06_AI_GOVERNANCE_AND_AUTONOMY_REVIEW.md
<full file content>
END_FILE

BEGIN_FILE: claude_worklog/v2_architecture_review/07_SECURITY_HOSTING_RBAC_REVIEW.md
<full file content>
END_FILE

BEGIN_FILE: claude_worklog/v2_architecture_review/08_RISK_GATEWAY_AND_LIVE_BLOCK_REVIEW.md
<full file content>
END_FILE

BEGIN_FILE: claude_worklog/v2_architecture_review/09_CONTINUOUS_MONITORING_AND_ATTRIBUTION_REVIEW.md
<full file content>
END_FILE

BEGIN_FILE: claude_worklog/v2_architecture_review/10_ARCHITECTURE_REVIEW_GO_NO_GO.md
<full file content must be exactly one line: V2_ARCHITECTURE_REVIEW_PASS or V2_ARCHITECTURE_REVIEW_FAIL>
END_FILE

Do not include any text outside BEGIN_FILE/END_FILE blocks.

Review criteria:
1. Verify architecture files 00–18 exist and are complete.
2. Verify every requirement 01–21 is represented.
3. Verify enterprise GUI is not a basic dashboard.
4. Verify passive market discovery and adaptive selection are fully represented.
5. Verify dynamic symbol universe supports add/remove/update without full service restart.
6. Verify hot-reload propagates to ingestors, feature pipeline, trainer adapter, orchestrator, risk gateway, trader fleet, monitor, and GUI.
7. Verify all available coins from Binance Futures, CoinAnk, CoinAPI, KuCoin, future futures exchanges, and future ingestors are passively monitored.
8. Verify Binance Futures is first connector but future futures exchanges are pluggable.
9. Verify multi-trader fleet is supported.
10. Verify feature attribution and signal explainability are mandatory.
11. Verify Claude/Codex/Ollama governance L0–L5 is represented.
12. Verify public hosting/security/RBAC are represented.
13. Verify Risk Gateway remains final authority.
14. Verify live trading remains blocked by default.
15. Verify continuous monitoring/evidence packets/trainer liveness are included.
16. Verify 100x–1000x mission alignment is present but bounded by survival, risk, replay, attribution, and human approval gates.

PASS only if architecture is ready for Codex adversarial architecture review.
Do not build V2 code.
