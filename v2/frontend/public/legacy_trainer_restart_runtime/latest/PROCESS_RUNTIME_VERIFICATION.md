# Process Runtime Verification

Generated: 2026-05-12T16:50:13Z

Classifications: `LEGACY_ORCHESTRATOR_OBSERVED_READONLY, LEGACY_TRADER_OBSERVED_READONLY, LEGACY_TRAINER_MONITOR_PROCESS_NOT_OBSERVED, LEGACY_TRAINER_PROCESS_OBSERVED, V2_PAPER_RUNTIME_OBSERVED`

| PID | PPID | Uptime seconds | Runtime root | CWD | Classification | Command |
|---:|---:|---:|---|---|---|---|
| 1042465 | 1011413 | 297078 | AI BOT | `/home/wali/Desktop/AI BOT` | LEGACY_ORCHESTRATOR_OBSERVED_READONLY | `python3 -m rl.orchestrator_worker` |
| 3324274 | 3324271 | 54700 | AI BOT | `/home/wali/Desktop/AI BOT` | LEGACY_TRADER_OBSERVED_READONLY | `python3 -u trading/trader.py` |
| 3446733 | 1011413 | 47169 | AI BOT REBUILD | `/home/wali/Desktop/AI BOT REBUILD` | V2_PAPER_RUNTIME_OBSERVED | `python3 -m v2.backend.app.cli.paper_online_runtime --loop --interval 30` |
| 3980694 | 3980692 | 2466 | AI BOT | `/home/wali/Desktop/AI BOT` | LEGACY_TRAINER_PROCESS_OBSERVED | `python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features` |

The manually started legacy trainer is attached to `/home/wali/Desktop/AI BOT`; V2 paper runtime remains attached to `/home/wali/Desktop/AI BOT REBUILD`. No process was stopped or restarted by this task.
