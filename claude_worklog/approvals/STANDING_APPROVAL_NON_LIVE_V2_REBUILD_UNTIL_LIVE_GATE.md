# Standing Approval: Non-Live V2 Rebuild Until Final Live Gate

The user authorizes autonomous Claude/Codex/Ollama execution for non-live V2 rebuild work inside:

/home/wali/Desktop/AI BOT REBUILD

Allowed autonomous work:
- local V2 scaffold implementation
- local backend/API development
- local database migration skeletons and offline migration tests
- local enterprise website/frontend development
- local ingestor adapter/wrapper development
- local feature pipeline development
- local trainer service rebuild based on legacy trainer behavior
- local trader fleet skeleton and paper/shadow adapters
- local risk gateway
- local replay/paper/shadow test framework
- local monitoring/evidence packet system
- local agent supervisor/dashboard work
- local tests, CI, static validation, contract validation
- Claude/Codex/Ollama review/remediation loops
- Git commits and GitHub pushes for safe artifacts

Still forbidden without explicit final/live approval:
- changes to /home/wali/Desktop/AI BOT
- Redis writes/deletes to legacy/live Redis
- live service restarts
- live trading
- exchange order placement/cancellation
- leverage/margin changes
- deployment
- production database migrations
- secrets exposure
- committing secret values
- sending secret values to Claude/Codex/Ollama prompts
- any L4/L5 action

Execution rules:
- The supervisor may automatically continue through 015B-015F and subsequent non-live local rebuild tasks.
- The supervisor must run one implementation milestone at a time.
- Codex must review each milestone before moving to the next.
- Claude may remediate failed Codex reviews automatically if the remediation is non-live and stays inside AI BOT REBUILD.
- If a task attempts live/legacy/Redis/exchange/deploy behavior, stop and mark human_attention_required.
- If a task touches secrets, it must use local ignored files only and must not print values.

Final live approval is still required before:
- live exchange actions
- live trading
- production deployment
- live Redis writes
- legacy bot replacement
- any production migration

STANDING_APPROVAL_NON_LIVE_V2_REBUILD_UNTIL_LIVE_GATE
