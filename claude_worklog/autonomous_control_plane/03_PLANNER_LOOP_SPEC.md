# Planner Loop Specification

Planner cycle:
1. read master objective
2. read current git status
3. read queue_status/current_status
4. read latest gates
5. read monitoring/evidence packet summaries
6. ask Ollama to summarize large evidence if needed
7. ask Claude to propose next task(s)
8. ask Codex to review plans when needed
9. supervisor writes task JSONs
10. supervisor executes allowed tasks
11. supervisor commits safe outputs
12. dashboard updates
13. stop only on gates requiring human

PLANNER_LOOP_SPEC_READY
