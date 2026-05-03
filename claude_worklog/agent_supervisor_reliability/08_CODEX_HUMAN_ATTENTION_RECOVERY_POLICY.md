# Codex Human Attention Recovery Policy

## Purpose

Codex should resolve recoverable non-live `human_attention_required` blockers without waiting for the human operator.

## Scope

Codex has full remediation authority inside AI BOT REBUILD for non-live work.

## Still human-only

- final live approval
- live trading enablement
- live Redis writes/deletes
- live service restarts
- exchange actions
- production deployment
- secret exposure decisions
- L4/L5 actions

## Recovery examples

Codex may automatically fix:

- wrong emitted output path
- missing required output file
- stale runtime state
- failed tests
- incomplete validation log
- missing Codex PASS evidence
- planner evidence-wire bug
- dashboard stale-state display
- safe path remap rule gap
- task prompt emit-format failure
- harmless documentation mismatch

## Required validation

Every Codex recovery must include:

- local validation
- high-confidence secret scan
- safety scan for live/Redis/legacy/exchange/deploy terms
- commit/push
- Codex re-review or evidence marker

CODEX_HUMAN_ATTENTION_RECOVERY_POLICY_READY
