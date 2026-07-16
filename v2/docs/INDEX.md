# V2 Documentation Index

## Current reverse-engineered system

- [System entry point](../../docs/MASTER_SYSTEM_DOC.md)
- [Reverse-engineering package](../../docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md)
- [Low-level technical reference](V2_SYSTEM_TECHNICAL_REFERENCE.md)
- [Operator manual](../../docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md)
- [Current risk register](../../docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md)
- [Validation and limitations](../../docs/system_audit_2026_master/VALIDATION_AND_LIMITATIONS_2026-07-16.md)
- [Historical artifact classification](../../docs/system_audit_2026_master/HISTORICAL_ARTIFACT_CLASSIFICATION.md)
- [Rebuild blueprint](../../docs/system_audit_2026_master/REBUILD_BLUEPRINT.md)
- [Function/module atlas](../../docs/system_audit_2026_master/atlas/ATLAS_SUMMARY.md)
- [Exact audit command ledger](../../docs/system_audit_2026_master/COMMANDS_RUN.md)

The system is mutable. Runtime counts and process state in the audit are timestamped
snapshots; code contracts and static inventories must be regenerated after source
changes with `python3 tools/build_system_reverse_engineering_atlas.py`.

## Historical planning artifacts

These are design-time inputs, not proof of the currently deployed behavior:

- `claude_worklog/v2_scaffold_planning/02_PACKAGE_AND_MODULE_MAP.md`
- `claude_worklog/v2_architecture/05_API_CONTRACTS.md`
- `claude_worklog/v2_architecture/15_PUBLIC_HOSTING_SECURITY_AND_RBAC_ARCHITECTURE.md`
- `claude_worklog/v2_architecture/17_IMPLEMENTATION_SEQUENCE_AND_MILESTONES.md`
- Milestone B scaffold validation: `claude_worklog/v2_build/B_SCAFFOLD_VALIDATION.md`
