# V2 Orchestrator Arbitration P0.3 - Native Paper-First

Phase P0.3; Sprint 12h native core migration.

Generated: 2026-05-16T04:35:00Z
Git HEAD: 31a7fd70319f0d586c454b5ea2ea530ba9cb1541

## What was built

Existing scaffolding under
v2/backend/app/services/orchestrator_arbitration/ (service.py,
proposal.py, signal_schema.py, deconflict.py, stream_routing.py) was
wired end-to-end with the P0.2F trainer output:

- Trainer output -> proposal + V2Signal via a small projection.
- Proposal scoring with default 300s max_age_seconds (stale -> -inf).
- Signal schema validates required fields and unit-interval bounds.
- Deconflict returns ALL_SIGNALS_AGREE_ON_SIDE or
  MISSING_EVIDENCE_CANNOT_COMPARE when no signals are present.
- StreamRouter labels are informational only (primary, asjad, shadow).
- Public payload at
  v2/frontend/public/operator_runtime/v2_orchestrator_arbitration/latest/
  v2_orchestrator_arbitration_status.json updated with arbitration
  bucket winners + deconflict + safety invariants.

## End-to-end run (against live P0.1 snapshot)

- arbitration_considered_count: 1
- arbitration_bucket_winners: BTCUSDT short, score 0.567, EM after
  cost -68.46 bps, conf_cal 0.565.
- deconflict.conflict_reason: ALL_SIGNALS_AGREE_ON_SIDE.
- deconflict.selected_side: short.
- approves_live: false
- live_blocked: true
- live_gate: blocked_human_only
- cannot_bypass_risk_gateway: true
- orchestrator_overrides_risk: false
- exchange_action_taken: false
- redis_client_imported: false
- network_io_performed: false

## Legacy citations

- v2/legacy_owned_runtime/rl/orchestrator_worker.py
  sha256=a7ff83f992c6b0add14e4563241080cce431906642c0de6aa778d3fb9eb217c6
- v2/legacy_owned_runtime/rl/proposal_bus.py
  sha256=e6c7657b7b70d32773792005274d9d1bb08df8bce45c95c86e67e1fc61f0934d
- v2/legacy_owned_runtime/rl/tradeplan_orchestrator.py
  sha256=1e4ad19faed9dc3498f15401dc1065f1e1eedb400a662fc7272bed7df12fa4d0
- v2/legacy_owned_runtime/rl/intent_engine.py
  sha256=7d8d474237f08f3ab1f2775044f6e535c0a3934eb336c757b2cf4443f18b0975
- v2/legacy_owned_runtime/rl/action_ontology.py
  sha256=961a0e418a723d790d4cc692fe337cdd2e383b0b53963efbdc051c12d6a7b9ce
- v2/legacy_owned_runtime/rl/hybrid_action_space.py
  sha256=abc7ecf1e655e4a018eeedcb4ad675c7bb35e101d4b5a42d432132243aed6c23
- v2/legacy_owned_runtime/rl/hedge_action_space.py
  sha256=bf7869acba78d469a53ca101425284477c66a6e011e9ae6613e8d4bee79b3b70

## What is NOT migrated (explicit blockers)

- full_10523_line_orchestrator_worker_arbitration_logic
- live_order_routing
- live_redis_proposal_bus_integration
- hedge_cage_arbitration_overlays
- asjad_account_publish_path
- intent_engine_higher_timeframe_consensus_full_runtime
- tradeplan_orchestrator_protection_demand_score

These are explicit in components_missing_in_v2 of the public payload.

## Permanent migration contract checklist

- Legacy source paths: yes (6 files cited).
- SHA256: yes.
- Dependency closure: yes (no torch, no redis, no exchange SDK).
- Config/env mapping: max_age_seconds=300 default.
- Behavior mapping: yes (proposal scoring, stale handling, signal
  validation, deconflict, stream routing).
- V2 implementation: yes.
- Tests: 21 existing tests still pass.
- Public payload: yes (v2_orchestrator_arbitration_status.json).
- Codex review: pending.
- No old Redis writes: yes.
- No exchange mutation: yes.
- live_gate == "blocked_human_only": yes.
- live_symbols == []: yes.

## Decision

P0.3 is READY at the native paper-first arbitration contract level
with the V2 trainer output piped end-to-end. Full live arbitration
parity remains gated on the components_missing_in_v2 list.
