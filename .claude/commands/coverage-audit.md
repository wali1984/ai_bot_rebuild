---
description: Build complete legacy coverage manifest and block on unknowns.
---

Run complete coverage audit.

Do not build V2.

Required outputs:
- claude_worklog/coverage/FILE_MANIFEST.md
- claude_worklog/coverage/FILE_MANIFEST.json
- claude_worklog/coverage/SCRIPT_REGISTRY.md
- claude_worklog/coverage/SCRIPT_DEPENDENCY_GRAPH.md
- claude_worklog/coverage/RUNTIME_PROCESS_MAP.md
- claude_worklog/coverage/REDIS_KEY_STREAM_MAP.md
- claude_worklog/coverage/EXCHANGE_ACTION_MAP.md
- claude_worklog/coverage/STARTUP_PATH_MAP.md
- claude_worklog/coverage/UNKNOWN_GAPS.md

No unsafe_unknown items may remain before V2 build.
Every claim must include raw evidence pointer and verification command.
