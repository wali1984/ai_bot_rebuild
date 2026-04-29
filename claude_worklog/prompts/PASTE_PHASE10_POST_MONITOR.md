# After monitor completes — paste into Claude Code

Read all files in ./claude_worklog/monitoring and produce:

- ./claude_worklog/13_MONITORING_SUMMARY.md
- ./claude_worklog/14_RUNTIME_TRUTH_TABLE.md
- ./claude_worklog/15_SAFETY_CRITICAL_GAPS.md
- ./claude_worklog/16_V2_BUILD_GO_NO_GO.md

Required sections:
1. Redis streams observed
2. Heartbeats observed
3. Signals observed
4. Executions observed
5. Missing signal_id count
6. Missing confidence count
7. Duplicate exchange_order_id count
8. Stale signal count
9. CROSS margin observations
10. High leverage observations
11. ADJUST_LEVERAGE observations
12. Risk rejects/skips
13. Latency distribution
14. Docs that were false or unverified
15. Safety gaps V2 must fix
16. Whether V2 build may begin
