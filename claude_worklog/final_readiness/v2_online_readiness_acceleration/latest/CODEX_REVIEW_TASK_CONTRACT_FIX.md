# Codex Review Task Contract Fix

Task:
`codex_review_online_readiness_aggregator_freshness_extension`

## Problem

The original Codex review prompt allowed ambiguity: the task definition
allowed only:

```text
claude_worklog/final_readiness/v2_online_readiness_acceleration/latest/
```

but the first Codex run emitted files under:

```text
claude_worklog/final_readiness/online_readiness_codex_review/latest/
```

The supervisor correctly rejected that run because the emitted paths were
outside `allowed_output_prefixes` and the required files were missing.

## Fix

The task definition was patched so the canonical review contract is:

```text
claude_worklog/final_readiness/v2_online_readiness_acceleration/latest/ONLINE_READINESS_AGGREGATOR_FRESHNESS_CODEX_REVIEW.md
claude_worklog/final_readiness/v2_online_readiness_acceleration/latest/ONLINE_READINESS_AGGREGATOR_FRESHNESS_CODEX_GO_NO_GO.md
```

The prompt now explicitly forbids emitting under
`claude_worklog/final_readiness/online_readiness_codex_review/latest/`.

## State reconciliation

The retry completed under the correct prefix, and canonical mapping files
were created from accepted supervisor output plus the original stdout test
evidence. The task state is completed; stale retry metadata was cleared
from `resume_after_utc` and `last_retry_reason`.

## Scope

This is output-contract reconciliation only. It does not rerun
`claude_primary_v2_online_readiness_acceleration` and does not modify live,
legacy, Redis, exchange, leverage, margin, position mode, or service state.
