# Orchestrator / Trader Runtime Evidence

Generated: 2026-05-12T01:33:26.478561+00:00

Read-only process evidence.

```text
1042465 1011413 python3 -m rl.orchestrator_worker
1272209 1272100 tail -f Desktop/AI BOT/logs/orchestrator_worker.log
1272469 1272294 python3 Desktop/AI BOT/monitor_portfolio_primary.py
3324271 1011413 /bin/bash -O extglob -c snap=$(command cat <&3) && builtin shopt -s extglob && builtin eval -- "$snap" && { builtin set +u 2>/dev/null || true; builtin eval "${__CURSOR_SANDBOX_ENV_RESTORE:-}" 2>/dev/null; builtin export PWD="$(builtin pwd)"; builtin shopt -s expand_aliases 2>/dev/null; builtin eval "$1"; }; COMMAND_EXIT_CODE=$?; dump_bash_state >&4; builtin exit $COMMAND_EXIT_CODE -- cd "/home/wali/Desktop/AI BOT" && mkdir -p .logs && nohup python3 -u trading/trader.py >> .logs/trader.log 2>&1 & disown; sleep 1; pgrep -af "python3( -u)? trading/trader\.py" || true
3324274 3324271 python3 -u trading/trader.py
```

## Required V2 impact
- decisions must include decision_id
- risk gateway must default-deny stale/unsafe signals
- paper ledger must capture open/close/reduce/hedge/block
- shadow mode must compare legacy vs V2
