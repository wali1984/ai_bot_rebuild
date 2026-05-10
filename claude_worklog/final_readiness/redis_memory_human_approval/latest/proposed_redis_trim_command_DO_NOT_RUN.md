# Proposed Redis Trim Command - DO NOT RUN

This file documents the command for human review only. It was not executed.

Preferred time-based command:

```bash
redis-cli XTRIM liquidations:events MINID ~ 1777183314403-0
```

Alternate count-based command:

```bash
redis-cli XTRIM liquidations:events MAXLEN ~ 5000000
```

Expected memory reduction: 10183.355 MB

Prerequisites before running any command:
- Full export/offload manifest verified.
- Consumer group safety rechecked immediately before trim.
- Explicit human approval recorded.
- Live trading remains blocked.

DO_NOT_RUN_WITHOUT_EXPLICIT_HUMAN_APPROVAL
