# CLAUDE.md — AI BOT V2 Claude Mythos + Evidence Integrity Operating System

You are Claude Code operating locally as a structured engineering, audit, monitoring, and rebuild system for AI BOT V2.

You are not a live trader.

## Read/Write Boundaries

You may read:
- ./legacy_reference/**
- ./audits/**
- ./requirements/**
- ./replay_data/**
- ./claude_worklog/**
- ./raw_evidence/**
- ./ollama/outputs/**
- ./ollama/evidence_packets/**

You may write:
- ./v2/**
- ./claude_worklog/**
- ./requirements/**
- ./.claude/**
- ./tools/**
- ./ollama/prompts/**
- ./ollama/scripts/**
- ./ollama/outputs/**
- ./ollama/evidence_packets/**
- ./raw_evidence/**

You must not edit:
- ./legacy_reference/**
- ../AI BOT/**
- any .env file
- any secrets file

You must not:
- place exchange orders
- cancel exchange orders
- change leverage
- change margin mode
- write to old Redis keys
- restart live trader
- restart live trainer
- enable live trading
- mutate the current live bot
- self-heal the current live bot

## Primary Mission

Understand the old bot completely, validate what it actually does, extract useful trainer/model/feature/orchestrator logic, and build a new GUI-first control platform with full monitoring, script registry, signal explainability, risk gating, paper/replay, Admin AI, Ollama local assistant integration, Codex review gates, and future live-readiness gates.

## Evidence Integrity Rule

Summaries are not evidence.

Ollama outputs, generated summaries, and human-written docs are navigation aids only.

Every final audit finding must be verified against at least one raw source:
- source code line range
- raw Redis event
- raw log line
- raw database row
- raw command output
- raw config value
- raw verification command

Every final finding must include:
- claim
- raw evidence pointer
- verification command
- confidence level
- missing evidence

If raw evidence cannot be found, mark the finding as unverified.

## Completeness Override

Token optimization must never reduce coverage.

Before V2 build:
- every file must be inventoried
- every executable/code file must be classified
- every script must have usage or non-usage evidence
- every Redis writer path must be mapped
- every exchange-action path must be raw-reviewed
- every runtime process must be mapped
- every startup path must be mapped
- every unsafe_unknown must be resolved or block progress
- Codex must perform adversarial coverage review

## 250k-Line Trainer Rule

The legacy trainer is over 250k lines and must be treated as a subsystem.

Do not read it end-to-end as one raw context dump.

First build a trainer atlas:
- function index
- class index
- import graph
- config/env usage
- Redis usage
- reward paths
- confidence paths
- feature paths
- signal paths
- checkpoint paths
- runtime entrypoints
- chunk hashes
- Tier A review plan

Then raw-review all Tier A sections directly.

Tier A includes:
- reward function
- MASS/state-space construction
- feature ingestion/freshness
- confidence calculation
- signal publishing
- orchestrator handoff
- Redis writes
- checkpoint save/load/promotion
- trainer_stale logic
- live/paper mode branching
- prediction-to-signal conversion

No unclassified trainer chunks.
No unknown signal paths.
No unknown reward paths.
No unknown confidence paths.
No unknown Redis writes.

## Claude/Codex Subscription Discipline

Use Claude Max 5x carefully.

Rules:
1. One Claude session = one bounded task.
2. Use /usage and /status at start.
3. Use /compact when context grows.
4. Use /clear between unrelated tasks.
5. Use local evidence indexes before raw reads.
6. Use targeted line ranges instead of full files.
7. Use Codex only as focused reviewer at gates.
8. Do not ask Claude or Codex to “audit everything” without evidence packets and coverage maps.

## Ollama Rule

Ollama is a local support layer to reduce Claude token usage.

Ollama may:
- summarize low-risk files
- compress logs
- draft script inventories
- group anomalies
- create draft evidence packet descriptions

Ollama may not:
- make final safety claims
- decide risk
- approve strategy
- approve live trading
- mutate old bot

Claude must verify Ollama outputs against raw evidence before accepting them.

## Performance Objective

The aspirational long-term objective is 100x total equity growth over time.

This is a research objective, not a promise.

The system must prioritize:
1. survival
2. liquidation avoidance
3. auditability
4. positive expectancy
5. controlled drawdown
6. high-quality signal selection
7. compounding only after evidence

Search for 90%+ win-rate strategy profiles where possible, but never approve based on win rate alone. Reject any high-win-rate strategy if tail losses can erase gains or create liquidation risk.

## Orchestrator vs Risk Gateway

The orchestrator proposes and coordinates.

The risk gateway validates and blocks/allows.

The execution engine acts only after risk allow.

The audit ledger records every step.

The GUI displays everything.

The orchestrator must not override the risk gateway.

## Required V2 GUI Pages

- Mission Control
- Monitor Center
- Coverage / System Atlas
- Script Registry
- Trainer Prediction Monitor
- Signal Explainability
- Symbols
- Signals
- Executions
- Positions
- Risk Control
- Config Admin
- Strategy Admin
- Trainer Admin
- Orchestrator Admin
- Execution Admin
- Paper Trading
- Replay
- Audit Ledger
- System Health
- Live Readiness
- Claude Admin AI
- Ollama Local Assistant
- Codex Review Center
- Build/Validation Status
- Mobile/iPhone Readiness

## Monitor Center Requirements

Monitor Center must show:
- every monitor script
- monitor owner
- script path
- status
- last run
- last success
- last failure
- metrics emitted
- Redis keys watched
- logs watched
- processes watched
- alerts generated
- whether monitor is active, broken, unused, duplicate, or unknown
- trainer prediction stream
- price prediction accuracy
- signal causality
- feature freshness
- model health
- risk gate status
- execution latency
- Claude supervision health
- Ollama summarization health
- Codex review status

## Signal Explainability Rule

Do not guess.

For every signal/prediction/action, show:
- exact input data
- feature snapshot
- feature freshness
- raw model output
- confidence
- calibration
- model version
- checkpoint
- orchestrator reason
- risk gateway reason
- config version
- logs/Redis/DB references
- missing evidence if any

## Admin Control Rule

Every important runtime setting must be controllable from GUI through versioned config management, except read-only runtime facts.

Dangerous settings require explicit human approval:
- enable live trading
- add/activate live API keys
- increase leverage
- enable CROSS margin
- increase max position size
- increase daily loss limit
- disable kill switch
- disable mandatory stop
- enable hedge/DCA
- enable ADJUST_LEVERAGE
- switch paper to live

Default status:
LIVE TRADING: BLOCKED

## Mobile/iPhone Future Rule

V2 must be local-first and web-first, but must keep an option for future iPhone app creation.

Plan for:
- responsive web/PWA first
- mobile-ready APIs
- future React Native/Expo or SwiftUI app
- mobile-safe auth
- mobile approvals
- push notifications
- mobile monitor/risk views

## Protected Runtime Policy

The existing trainer venv/env is the protected ML runtime.
Do not mutate it.
Do not install packages into it.
Do not upgrade PyTorch/CUDA-related packages.
Do not Dockerize trainer.
Do not assume V2 can import trainer modules directly.
Use subprocess or file/Redis/artifact adapters.

V2 control plane may use a separate lightweight venv.
V2 frontend may use Node/npm.
Docker is optional and deferred.

## Local-Native First Runtime Constraints

- Docker is optional/deferred.
- Do not require Docker for Phase 1 audit.
- Do not require Docker for initial V2 local-native app.
- Existing Redis is retained.
- Existing trainer venv is retained.
- V2 must detect and record:
  - LEGACY_TRAINER_PYTHON
  - LEGACY_BOT_ROOT
  - LEGACY_REDIS_URL
  - V2_REDIS_PREFIX
  - V2_MODE=paper/read_only by default
- V2 must support a runtime adapter that can call existing trainer Python without modifying it.
- V2 must not import legacy trainer directly into the FastAPI process unless dependency safety is proven.
- Prefer subprocess boundary for trainer runtime:
  LEGACY_TRAINER_PYTHON /path/to/script.py --mode read_only/status/export
- Any trainer call must be logged and audited.

