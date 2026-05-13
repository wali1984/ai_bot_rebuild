# Remaining Live Blockers

Generated: 2026-05-13T04:22:07.783209Z

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

Live remains `blocked_human_only`. No approval file was created.
