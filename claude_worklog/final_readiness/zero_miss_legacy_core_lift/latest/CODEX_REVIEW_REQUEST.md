# Codex Review Request — Zero-Miss Legacy Core Lift

Status: PENDING_CODEX_REVIEW
Generated: 2026-05-15
Runtime gate: blocked_human_only. Runtime symbols: [].

## Scope

Adversarial review of the zero-miss legacy core ownership lift sprint.
Verify the following honestly:

1. v2/legacy_owned_runtime/ was populated from v2/legacy_preserved/ (277
   files) and not from the legacy bot root, which the runtime classifier
   denied.
2. zero_miss_dependency_closure.py scanned 246 .py files, reported 1
   unresolved local import (tools), 23 external dependencies, and 2
   syntax-error files.
3. FUNCTION_CLASS_CONFIG_ATLAS.json and TRAINER_ZERO_MISS_ATLAS.json
   contain the 468/930 class/function decomposition without invented
   entries.
4. Six V2-owned smoke CLIs ran, all with smoke_pass=true and
   legacy_root_rejected_count=0. No module file resolved under the
   legacy bot root.
5. V2_OWNED_RUNTIME_IMPORT_PROOF.json, REDIS_NAMESPACE_ISOLATION_PROOF.json,
   EXCHANGE_FAIL_CLOSED_PROOF.json, CONFIG_PARITY_MATRIX.json all hold
   the documented safety invariants.
6. 16 integration tests pass.
7. No approval token (live, canary, legacy shutdown, Redis trim) appears.

## Codex blocking conditions

Block if any of:

- A worker or wrapper is labeled MIGRATED_CODEX_PASS without satisfying
  every clause of the migration completion contract.
- Any approval token appears.
- Old Redis writes appear in the new code paths.
- Exchange mutation appears.
- The atlas or dependency closure shows invented data.
- A wrapper resolves a module file under the legacy bot root.
- The 1,917 legacy config keys are claimed mapped without operator
  decision evidence.
- The two syntax-error files are hidden or omitted from the BLOCKED list.

## Expected outcome

A CODEX_REVIEW.md in this directory with the top line:

GO/NO-GO: CODEX_REVIEW_ZERO_MISS_LEGACY_CORE_LIFT_PASS
or FAIL, plus findings.

This review does not authorize live, canary, legacy shutdown, or Redis
trim.
