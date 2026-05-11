# Online Readiness Codex Output Contract Mapping

## Canonical contract

Canonical directory:

```text
claude_worklog/final_readiness/v2_online_readiness_acceleration/latest/
```

Canonical files:

```text
ONLINE_READINESS_AGGREGATOR_FRESHNESS_CODEX_REVIEW.md
ONLINE_READINESS_AGGREGATOR_FRESHNESS_CODEX_GO_NO_GO.md
ONLINE_READINESS_AGGREGATOR_FRESHNESS_TEST_RESULTS.md
```

Canonical GO/NO-GO value:

```text
ONLINE_READINESS_AGGREGATOR_FRESHNESS_CODEX_PASS
```

## Source paths

Rejected stdout source path:

```text
claude_worklog/agent_supervisor/runs/codex_review_online_readiness_aggregator_freshness_extension/stdout.txt
```

Accepted supervisor review path:

```text
claude_worklog/final_readiness/v2_online_readiness_acceleration/latest/CODEX_ONLINE_READINESS_AGGREGATOR_FRESHNESS_REVIEW.md
```

Accepted supervisor GO/NO-GO path:

```text
claude_worklog/final_readiness/v2_online_readiness_acceleration/latest/CODEX_GO_NO_GO.md
```

Deprecated/source-only prefix from the rejected run:

```text
claude_worklog/final_readiness/online_readiness_codex_review/latest/
```

## Marker normalization

Source marker:

```text
CODEX_ONLINE_READINESS_AGGREGATOR_FRESHNESS_PASS
```

Canonical marker:

```text
ONLINE_READINESS_AGGREGATOR_FRESHNESS_CODEX_PASS
```

## Interpretation

The canonical files are mapping/reconciliation artifacts. They do not claim
new implementation evidence. The review evidence comes from:

- the accepted supervisor retry under the V2 online readiness prefix, and
- the first rejected stdout run, which included a valid PASS review and
  `23 passed` unit-test evidence.
