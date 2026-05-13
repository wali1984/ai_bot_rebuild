# Always-On Objective Runner Policy

Generated: 2026-05-13T03:04:28.450818+00:00

## Purpose
`claude_worklog/tools/always_on_objective_runner.py` enforces a never-empty primary objective loop for AI BOT V2. It writes only inside AI BOT REBUILD and never has authority to mutate the legacy bot, old Redis, exchange state, leverage, margin, or live trading.

## Loop Rules
Every cycle the runner checks Claude/Codex child processes, selected task, queue freshness, paper runtime, CoinAnk bridge status, dirty git classification, final live gate, and current readiness markers.

If Claude is idle and no valid blocker exists, the runner selects or creates the next primary V2 task. If Codex has safe audit work available, it creates non-live Codex audit task definitions. If all primary build tasks are complete, the runner falls back to recurring non-live monitor/audit tasks instead of stopping.

## Current Selection
- Selected primary task: RISK_GATEWAY_RUNTIME_EXPANSION_TESTS
- Selection action: existing_pending
- Live gate: blocked_human_only
- CoinAnk remediation marker: COINANK_PLAN3_RUNTIME_CONTRACT_REMEDIATION_AND_V2_REAUDIT_READY

## Human Stops
The runner must stop at `FINAL_LIVE_CAPITAL_APPROVAL_REQUIRED`. It cannot approve live capital, create a Redis trim approval, enable live keys, or bypass human approval.
