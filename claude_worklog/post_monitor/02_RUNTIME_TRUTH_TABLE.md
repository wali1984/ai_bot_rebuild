# 02 Runtime Truth Table

| Check | Evidence | Result |
|---|---|---|
| Monitor reached natural completion | `monitoring_summary.md` shows `Finished` and `Reason: duration_complete` | TRUE |
| Snapshots captured | `snapshots.jsonl` has 720 lines | TRUE |
| Trainer metrics captured | `trainer_metrics.jsonl` has 720 lines | TRUE |
| Runtime duration is ~12h | First/last snapshot timestamps span 11.991h | TRUE |
| Snapshot cadence stable | Delta min/max/avg ≈ 60.03/60.06/60.04 sec | TRUE |
| Redis ping healthy during run | `redis_ping_ok` true on 720/720 ticks | TRUE |
| `signals:trading` stream showed zero xlen in snapshots | `stream_xlen.signals:trading == 0` on 720 ticks | TRUE |
| Executed signals observed elsewhere | `stream_xlen.executed_signals` ranged 1001–1065 | TRUE |
| Skip events present | `signals:execution:skips` ranged 5000–5005 | TRUE |
| Signal attribution completeness | Gap audit classification `FEATURE_KEY_MONITORING_PARTIAL` | FALSE (complete attribution not achieved) |
| Redis memory safety comfort | Dashboard observed memory ratio ~96.80% | FALSE (comfort threshold) |
| Monitor critical log errors | `read_only_monitor.log` empty | TRUE |
