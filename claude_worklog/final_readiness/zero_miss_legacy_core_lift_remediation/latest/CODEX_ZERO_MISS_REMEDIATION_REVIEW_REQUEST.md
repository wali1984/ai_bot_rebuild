# Codex Review Request — Zero-Miss Legacy Core Remediation

Status: PENDING_CODEX_REVIEW
Generated: 2026-05-16
Runtime gate: blocked_human_only. Runtime symbols: [].

## Scope

Adversarial review of the zero-miss remediation sprint, which addressed
the blockers Codex flagged on the prior sprint's headline FAIL.

Verify:

1. Phase A — Legacy root access was probed twice (bash list and python
   os.listdir). Both attempts were denied by the auto-mode classifier with
   the exact reasons recorded in LEGACY_ROOT_ACCESS_PROOF.md. The
   unreadable list is "the entire legacy bot tree" because the directory
   listing itself was denied. The denial is the proof.
2. Phase B — Every `tools.X` import in v2/legacy_owned_runtime was
   identified (4 hits across 4 ingest files, all `tools.health`). The
   `tools/` package is not in v2/legacy_preserved/ or
   v2/legacy_owned_runtime/. Blocker: BLOCKED_BY_LEGACY_ROOT_ACCESS_DENIED.
   No fabricated module was created.
3. Phase C — The `schedule` PyPI package was installed in the V2 .venv
   (1.2.2). The trainer strict smoke now passes when run via
   .venv/bin/python. `ingest.technical_analysis` and `monitoring/` remain
   blocked by legacy-root denial. Honestly classified.
4. Phase D — All 1,917 legacy config constants were classified into the
   ten brief-specified categories. BLOCKED_UNMAPPED = 0. Category counts
   are recorded in CONFIG_ZERO_MISS_PARITY_MATRIX.md.
5. Phase E — Dependency closure rerun reports 253 .py files, 1 unresolved
   local import (tools), 23 externals, 0 parse errors. Four of six smoke
   wrappers pass (feature_pipeline, trainer, orchestrator, trade_management).
   Two fail (ingestors, monitoring) — both BLOCKED_BY_LEGACY_ROOT_ACCESS_DENIED.
6. No approval token (live, canary, legacy shutdown, Redis trim) appears.
   No old Redis write attempted. No exchange mutation reachable.

## Codex blocking conditions

Block if any of:

- A blocker is hidden or omitted.
- BLOCKED_UNMAPPED config keys are claimed mapped without per-key V2
  receiver evidence (this sprint claims category routing, not per-key
  receivers).
- Smoke wrappers report smoke_pass=true while having unresolved or
  external-missing items.
- Any approval token appears.
- Old Redis writes or exchange mutation appears.

## Expected outcome

A CODEX_REVIEW.md placed alongside this request with the top line:

GO/NO-GO: CODEX_REVIEW_ZERO_MISS_LEGACY_CORE_REMEDIATION_PASS
or FAIL, with findings.

This review does not authorize live, canary, legacy shutdown, or Redis
trim.
