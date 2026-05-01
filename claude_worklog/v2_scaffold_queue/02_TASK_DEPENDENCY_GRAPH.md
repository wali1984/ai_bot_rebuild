# 02 — Task Dependency Graph

## 1. Purpose
Define the directed acyclic graph (DAG) of dependencies between queue tasks `015A`–`015F`. The supervisor consumes the `depends_on` field of each task JSON to enforce this graph at dispatch time. This document is the human-readable view of the same graph.

## 2. Nodes
- `015A` — Repo / package skeleton.
- `015B` — Database migration skeleton.
- `015C` — API route skeleton.
- `015D` — Enterprise frontend shell.
- `015E` — Test / CI skeleton.
- `015F` — Agent supervisor / dashboard integration.

## 3. Edges (parent -> child)
- `015A -> 015B`
- `015A -> 015E`
- `015B -> 015C`
- `015C -> 015D`
- `015A -> 015F`
- `015B -> 015F`
- `015C -> 015F`
- `015D -> 015F`
- `015E -> 015F`

## 4. ASCII rendering

```
              ┌──────────┐
              │  015A    │
              │ skeleton │
              └────┬─────┘
                   │
        ┌──────────┼──────────────┐
        ▼                         ▼
  ┌───────────┐              ┌──────────┐
  │  015B DB  │              │ 015E     │
  │ migration │              │ test/CI  │
  └─────┬─────┘              └────┬─────┘
        │                          │
        ▼                          │
  ┌───────────┐                    │
  │ 015C API  │                    │
  │  routes   │                    │
  └─────┬─────┘                    │
        │                          │
        ▼                          │
  ┌───────────┐                    │
  │ 015D GUI  │                    │
  │  shell    │                    │
  └─────┬─────┘                    │
        │                          │
        └──────────┬───────────────┘
                   ▼
            ┌───────────────┐
            │ 015F agent /  │
            │ dashboard     │
            │ integration   │
            └───────────────┘
```

## 5. Topological order (one valid linearization)
1. 015A
2. 015E (parallel with 015B if W1 parallelism is approved)
3. 015B
4. 015C
5. 015D
6. 015F

## 6. Cycle / conflict guarantees
- The graph is acyclic. The CI script `ops/ci/import_cycle_check.py` (materialized by 015E) re-checks the dependency declarations of each task against the actual import graph of `v2/**` and fails on any cycle.
- No task depends on a downstream milestone artifact (e.g., 015A does NOT depend on `K_RISK_VALIDATION.md`). Cross-milestone work is forbidden inside the scaffold queue.

## 7. Forbidden cross-edges
- 015A MUST NOT write under `v2/ops/ci/**` (that path is owned by 015E).
- 015B MUST NOT write under `v2/backend/app/api/v1/**` (that path is owned by 015C).
- 015C MUST NOT write under `v2/frontend/**` (that path is owned by 015D).
- 015D MUST NOT modify `v2/backend/migrations/**` (owned by 015B).
- 015F MUST NOT introduce any new write path under `v2/backend/app/api/v1/**` or `v2/frontend/src/pages/**`; it integrates dashboard endpoints by adding new route files under `v2/backend/app/api/v1/_meta/` and new components under `v2/frontend/src/components/dashboard/` only.

The supervisor's pre-dispatch path-validator enforces these forbidden cross-edges.

## 8. Dependency-failure semantics
- If `015B` fails, `015C`/`015D`/`015F` automatically transition to `blocked_dependency` (via the supervisor's dependency check) and remain there until 015B is re-run successfully.
- A task that is `blocked_approval` at dispatch time stays `blocked_approval` regardless of dependency state — human approval is the higher gate.

## 9. Status
DAG: DEFINED. ENFORCEMENT: SUPERVISOR `depends_on`. ROLLBACK: PER `00_QUEUE_OVERVIEW.md` §8.