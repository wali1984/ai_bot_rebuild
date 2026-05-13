# V2 Production Truth Reconciliation and Migration Execution Gate Report

Generated: 2026-05-13T04:22:07.783209Z

## Verdict

- Gate marker: `V2_PRODUCTION_TRUTH_RECONCILIATION_AND_MIGRATION_EXECUTION_GATE_READY`
- Production/live status: `BLOCKED_NOT_LIVE_READY`
- Paper/shadow status: `CURRENT_NON_LIVE_RUNTIME_ACTIVE`
- Live gate: `blocked_human_only`
- Approval file present: `False`

This packet is a truth reconciliation gate, not live approval. The system must not be described as live-ready because final approval packets and READY markers exist. Current runtime truth supports continued non-live paper/shadow operation and migration execution only.

## Current V2 Runtime Truth

- Market feed: `CURRENT`, age `8` seconds.
- Trainer prediction: `pred_paper_tick_1778646096231` from `v2_paper_readonly_momentum_wrapper_v1`.
- Feature snapshot: `fs_paper_tick_1778646096231`.
- Signal: `sig_paper_tick_1778646096231`.
- Orchestrator decision: `orch_paper_tick_1778646096231`.
- Risk decision: `risk_paper_tick_1778646096231` = `APPROVED_FOR_PAPER_ONLY` / `allow_proceed_long`.
- Paper execution: `FILLED_PAPER_ONLY`, exchange_order_id `None`.

## Migration Reality

- Total scripts tracked: `4194`.
- Active runtime scripts: `7`.
- Exchange-action references: `344`.
- Redis writer references: `445`.
- unsafe_unknown scripts: `2093`.
- Zero unclassified active runtime scripts: `True`.

## Remaining Live Blockers

- FINAL_GATE_MISSING_EVIDENCE: read-only account status, trade permission status, and weekly loss hard stop evidence are missing.
- SCRIPT_MIGRATION_UNSAFE_UNKNOWNS: 2093 scripts remain unsafe_unknown in migration backlog.
- EXCHANGE_ACTION_SCRIPT_MIGRATION_INCOMPLETE: 344 exchange-action references still require migration/containment mapping.
- REDIS_WRITER_MIGRATION_INCOMPLETE: 445 Redis writer references still require V2 namespace/durability migration.
- TRAINER_FULL_MODEL_PARITY_NOT_PROVEN: V2 wrapper is current but legacy PPO/MASA checkpoint parity is not claimed.
- POSTGRES_RUNTIME_CONNECTION_NOT_CONFIGURED: schema-ready only; runtime durable DB writes are not proven.
- V2_REDIS_RUNTIME_WRITES_DISABLED: bounded namespace contract exists but runtime writes are disabled for safety.
- COINANK_BRIDGE_PAYLOAD_STALE_OR_UNVERIFIED: generated_at age_seconds=11524; refresh cadence must be proven before production truth claim.
- OPERATOR_TRUTH_BRIDGE_PAYLOAD_STALE: generated_at age_seconds=1130; website truth bridge needs refresh before production truth claim.
- LEGACY_EXECUTED_ORDER_EVIDENCE_PRESENT: legacy stack has real exchange_order_id evidence; V2 must remain observer until cutover/containment is complete.
- LEGACY_CROSS_MARGIN_EVIDENCE_PRESENT: legacy observed position after execution shows cross margin; V2 canary requires isolated only.

## Legacy vs V2 Improvements Observed

- Current V2 paper runtime emits pred_*/fs_*/sig_*/orch_*/risk_*/pei_* lineage from real-time payload, not hist_* fixtures.
- Risk Gateway is final authority; the current V2 paper intent is approved for paper only and still produces no exchange_order_id.
- V2 paper ledger records paper-only outcomes, including simulated fills or risk blocks, without live orders.
- Legacy live bridge is read-only and V2 shadow risk blocks legacy-observed signals missing prediction_id/feature_snapshot_id.
- CoinAnk Plan-3 remediation is recorded as READY and market-intelligence payload labels source as LIVE_COINANK_READONLY.
- Website route rebuild and PageShell data layer expose current paper runtime IDs, risk status, and live-blocked banner from runtime payloads.

## Required Next Gate

Continue non-live migration execution. Do not request or create final live/capital approval until the hard blockers are reduced or explicitly accepted by the human operator in a separate approval gate.
