CLOSED_LOOP_TAKEOVER_CLAUDE_PRIORITY_OLD_REDIS_WRITER_PROOF_MISSING_20260531_CODEX_FAIL

BLOCKER: The paired Claude task did not emit the required `old_redis_writer_proof_missing` evidence triplet (`REPORT.md`, `STATUS.json`, `GO_NO_GO.md`) under `claude_worklog/final_readiness/priority_autoseed_20260531/old_redis_writer_proof_missing`, so V2-side canary/liveness proof evidence is incomplete and cannot be independently verified.

Policy state for this review remains strict: `live_gate=blocked_human_only`, `live_symbols=[]`; do not approve live, canary, legacy shutdown, or Redis trim.
