# Codex Output Contract Mismatch Diagnostic

Status: reconciled

## Source condition

`claude_primary_v2_online_readiness_acceleration` completed with:

```text
V2_ONLINE_READINESS_ACCELERATION_READY
```

The first follow-up Codex review run for
`codex_review_online_readiness_aggregator_freshness_extension` produced a
valid PASS review in stdout, but emitted `BEGIN_FILE` blocks under the
deprecated/source-only prefix:

```text
claude_worklog/final_readiness/online_readiness_codex_review/latest/
```

The supervisor task allowed and required:

```text
claude_worklog/final_readiness/v2_online_readiness_acceleration/latest/
```

## Rejected run evidence

- Run stdout:
  `claude_worklog/agent_supervisor/runs/codex_review_online_readiness_aggregator_freshness_extension/stdout.txt`
- Rejected source paths in stdout:
  - `claude_worklog/final_readiness/online_readiness_codex_review/latest/CODEX_ONLINE_READINESS_AGGREGATOR_FRESHNESS_REVIEW.md`
  - `claude_worklog/final_readiness/online_readiness_codex_review/latest/CODEX_GO_NO_GO.md`
- Rejected source PASS marker:
  `CODEX_ONLINE_READINESS_AGGREGATOR_FRESHNESS_PASS`
- Rejected run test evidence:
  `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/pytest -q -p no:cacheprovider v2/backend/tests/unit/proof/test_online_readiness_aggregator_freshness.py v2/backend/tests/unit/proof/test_online_readiness_aggregator.py` -> `23 passed in 0.04s`

## Accepted retry evidence

- Run summary:
  `claude_worklog/agent_supervisor/runs/codex_review_online_readiness_aggregator_freshness_extension/summary.json`
- Accepted supervisor files:
  - `claude_worklog/final_readiness/v2_online_readiness_acceleration/latest/CODEX_ONLINE_READINESS_AGGREGATOR_FRESHNESS_REVIEW.md`
  - `claude_worklog/final_readiness/v2_online_readiness_acceleration/latest/CODEX_GO_NO_GO.md`
- Accepted source marker:
  `CODEX_ONLINE_READINESS_AGGREGATOR_FRESHNESS_PASS`
- Accepted task state:
  `claude_worklog/agent_supervisor/state/tasks/codex_review_online_readiness_aggregator_freshness_extension.json`
  is `completed`.

## Diagnosis

The first failure was an output path contract mismatch only. It was not an
implementation failure and not a live-safety issue. The accepted retry
confirmed the same review result under the required prefix.

## Safety boundary

No legacy bot mutation, Redis write/delete/trim, exchange action, leverage
change, margin-mode change, position-mode change, live-key activation, live
execution enablement, or live service restart was required for this
reconciliation.
