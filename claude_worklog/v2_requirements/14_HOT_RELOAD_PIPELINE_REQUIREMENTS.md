# 14 Hot-Reload Pipeline Requirements

## Requirement ID
V2-HOT-RELOAD-PIPELINE-001

## Objective
Symbol universe and related policy updates must propagate platform-wide without full-system restart.

## Mandatory propagation targets
Every approved universe update must propagate to:
- ingestors
- feature pipeline
- trainer adapter
- orchestrator
- risk gateway
- trader fleet
- monitor
- GUI

## Required behavior
1. Restart-free updates
- Routine symbol universe updates must not require full platform restart.

2. Versioned update events
- Each update has immutable `universe_version` and change-set metadata.
- Version includes author, timestamp, reason, approval chain, and diff.

3. Deterministic rollout
- Publish/update/apply flow with explicit state transitions:
  - `proposed` → `validated` → `approved` → `applied` → `verified`

4. Component acknowledgment
- Each target component must ack applied version and health state.
- Missing ack triggers alert/escalation.

5. Rollback safety
- Fast rollback to last known-good universe version.
- Rollback event also audited.

## Validation and audit requirements
- For each update, persist:
  - requested change
  - validation result
  - approval evidence
  - component-wise apply status
  - post-apply health checks

## Safety constraints
- Live-trading-impacting universe changes require admin gate + readiness checks.
- Risk Gateway enforces final trade allow/block regardless of rollout status.

## Pre-architecture acceptance
- Update state machine, versioning, and component-ack protocol defined.
- Rollback and audit coverage defined.
