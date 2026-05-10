# Raw Evidence Pointers

- File manifest generated: FILE_MANIFEST.json via `python3 claude_worklog/tools/build_system_atlas_runtime_coverage.py`
- Runtime process map generated from ps: RUNTIME_PROCESS_MAP.json via `ps -eo pid,ppid,etimes,cmd`
- Redis map uses read-only redis-cli commands only when available: REDIS_KEY_STREAM_MAP.json via `redis-cli PING && redis-cli --scan`
- Exchange mutation tokens are mapped for raw review: EXCHANGE_ACTION_MAP.json via `regex scan over code-like files`
- 12-hour monitor not completed: runtime_monitor/runtime_monitor_status.json via `read runtime monitor status`
