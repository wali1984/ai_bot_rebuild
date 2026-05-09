# Phase 2X Legacy Evidence Review

Consulted evidence:
- `REQ_0013_SMC_LIQUIDITY_SHADOW_FEATURES.md` requires external/manual position quarantine before SMC or liquidity shadow-mode feature work.
- `REQ_0022_LEGACY_FAILURE_HEDGE_UNWIND_AND_SQUEEZE_RISK.md` requires typed protection against hedge-close residual exposure.
- `legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` records the LAB hedge-unwind short-squeeze failure mode.
- `replay_case_lab_hedge_unwind/01_LEGACY_FAILURE_EVIDENCE.md` provides the deterministic non-live fixture.
- `trainer_lineage_parity_fields_extension/02_PHASE_2V_TRAINER_LINEAGE_PARITY_FIELDS_SPEC.md` defines the five trainer-parity fields used by this contract.

The recovered implementation remains a typed non-live contract only. It does not consume exchange APIs, Redis, or live runtime services.

PHASE_2X_LEGACY_EVIDENCE_REVIEW_READY
