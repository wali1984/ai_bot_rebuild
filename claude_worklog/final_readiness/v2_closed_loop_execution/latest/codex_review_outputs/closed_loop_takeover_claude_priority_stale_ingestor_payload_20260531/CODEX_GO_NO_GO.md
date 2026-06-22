CLOSED_LOOP_TAKEOVER_CLAUDE_PRIORITY_STALE_INGESTOR_PAYLOAD_20260531_CODEX_FAIL

BLOCKER: The paired Claude task outputs were not materialized for audit under `claude_worklog/final_readiness/priority_autoseed_20260531/stale_ingestor_payload` (directory does not exist). Required files `STATUS.json`, `REPORT.md`, and `GO_NO_GO.md` are therefore missing, so the V2 stale-ingestor closure cannot be independently verified.

Policy is preserved for this review: `live_gate=blocked_human_only`, `live_symbols=[]`; do not approve live, canary, legacy shutdown, or Redis trim.
