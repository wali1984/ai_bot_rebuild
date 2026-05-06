# Parallel Capacity Scheduler Policy

## Purpose

Use Claude Code and Codex capacity in parallel without racing active output or loosening live safety boundaries.

## Operating model

Claude Code owns the active builder lane for the current paper/backtest MVP milestone.

Codex owns parallel review, non-live autofix, watchdog recovery, test-hardening review, and safety audit lanes.

Ollama may summarize logs and evidence when available, with no secrets.

## Scheduling rules

If a Claude child is active and Git is dirty, Codex may only run read-only review or diagnostics on already committed artifacts. Codex must not patch current dirty files or commit changes that race Claude output.

If no Claude child is active and Git is clean, Codex may patch non-live blockers, validate, secret-scan, commit, push, re-review, and restart the planner.

If no child is active and Git is dirty, Codex watchdog owns dirty-tree classification, runtime prompt restoration, planner-noise archiving, generated task validation, END_FILE cleanup, safe materialization recovery, commit, and planner restart.

If `human_attention_required` appears, Codex diagnoses and fixes it automatically unless a hard forbidden gate is involved.

If a Codex FAIL or implementation FAILED marker appears, Codex creates an autofix/recovery path, validates it, commits it, and re-reviews it.

## MVP priority

Until `V2_BACKTEST_AND_PAPER_MVP_READY`, all capacity must focus on:

- `TRAINER_PREDICTION_OUTPUT_MVP`
- `ORCHESTRATOR_DECISION_MVP`
- `RISK_GATEWAY_DEFAULT_DENY_MVP`
- `PAPER_EXECUTION_LEDGER_MVP`
- `REPLAY_BACKTEST_RUNNER_MVP`
- `PAPER_MODE_MVP`
- `SHADOW_MODE_READINESS`

## Hard forbidden actions

No automation lane may:

- modify `/home/wali/Desktop/AI BOT`
- write/delete Redis keys
- restart live services
- place/cancel orders
- change leverage/margin
- enable live trading
- deploy
- run production migrations
- expose or commit secrets
- bypass final live approval

## Status contract

The scheduler must publish:

- Claude lane active/idle/blocked
- Codex review lane active/idle/blocked
- Codex autofix lane active/idle/blocked
- Codex watchdog lane active/idle/blocked
- active Claude child
- active Codex child
- quota probe state
- latest Codex parallel review
- latest Codex autofix
- latest Codex watchdog recovery
- whether Codex is idle while safe work is available

PARALLEL_CAPACITY_SCHEDULER_POLICY_READY
