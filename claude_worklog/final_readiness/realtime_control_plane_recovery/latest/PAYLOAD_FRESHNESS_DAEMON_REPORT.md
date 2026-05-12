# Payload Freshness Daemon Report

Generated at: 2026-05-12T03:03:18.684Z

Command:

```bash
cd v2/frontend && npm run build:operator-truth
```

Freshness model:

- CURRENT: <= 120 seconds for runtime control-plane status
- WARN: 121-300 seconds
- STALE: > 300 seconds
- STATIC_PROOF_FIXTURE: never counted as runtime current
- MISSING: source absent/unreadable
- CONFLICTING: source disagrees with current process/git/status reality

Snapshot:

- payloads checked: 13
- stale: 12
- warn: 0
- static fixtures: 1
- missing evidence rows: 3
