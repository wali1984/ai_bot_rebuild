# Autonomous Non-Live V2 Rebuild Sequence

Standing approval:
STANDING_APPROVAL_NON_LIVE_V2_REBUILD_UNTIL_LIVE_GATE

Next implementation sequence after 015A:
1. 015B database migration skeleton
2. Codex review 015B
3. Remediate 015B if needed
4. 015C API route skeleton
5. Codex review 015C
6. Remediate 015C if needed
7. 015D enterprise frontend shell
8. Codex review 015D
9. Remediate 015D if needed
10. 015E test/CI skeleton
11. Codex review 015E
12. Remediate 015E if needed
13. 015F agent/dashboard integration
14. Codex review 015F
15. final scaffold integration review
16. legacy-compatible ingestor adapter phase
17. trainer parity rebuild phase
18. trader/risk gateway paper phase
19. replay/paper/shadow validation phase
20. live approval request phase

Rules:
- one implementation milestone at a time
- Codex review after every milestone
- do not run live trading
- do not write legacy Redis
- do not mutate legacy bot
- do not expose secrets
- stop on L4/L5
- stop on Codex hard fail that cannot be remediated
- stop on secret scan failure
- stop before final live approval

AUTONOMOUS_NON_LIVE_REBUILD_SEQUENCE_READY
