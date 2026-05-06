# Audit Sentinel Dirty Tree Policy

## Problem

Read-only audit sentinels refresh evidence files. Those refreshes can dirty Git and block the dispatch bridge.

## Policy

Audit outputs are durable evidence if they materially change or support current MVP work.

The Codex watchdog may auto-commit refreshed audit evidence when:

- no active Claude/Codex child is running
- files are inside allowed audit paths
- secret scan is clean
- safety scan shows no live/Redis/legacy/exchange/deploy action
- git dirty tree contains only audit evidence and runtime planner notes

## Runtime Prompt Files

Generated runtime prompt files must be restored or moved to runtime storage before dispatch.

## Safety

Read-only audit evidence must never include secret values or Redis values.

AUDIT_SENTINEL_DIRTY_TREE_POLICY_READY
