# Codex Review: Zero-Miss Legacy Core Remediation

Generated: `2026-05-16T00:34:01Z`

GO/NO-GO: `ZERO_MISS_LEGACY_CORE_REMEDIATION_CODEX_FAIL`

Superseded note: this Round 1 FAIL is retained as historical evidence. Round
2 closed the exact source ownership/import/smoke blockers and is reviewed in
`CODEX_ZERO_MISS_REMEDIATION_ROUND_2_REVIEW.md`.

## Decision

Codex fails `ZERO_MISS_LEGACY_CORE_REMEDIATION_READY`.

The remediation closed some prior issues, but it did not satisfy the user's fail gates. The packet remains blocked by unresolved source/import coverage and strict smoke failures. It does not approve live trading, canary trading, legacy shutdown, or Redis trim.

## Blocking Findings

1. `LEGACY_ROOT_READ_ACCESS_DENIED` remains in the remediation packet.
   - Remediation payload: `legacy_root_access_proof.json` reports `read_access_to_legacy_root=false`.
   - Codex shell can read legacy-root metadata, so the practical blocker is now that the remediation did not consume available safe legacy sources into V2 ownership.

2. Safe legacy source files are present in the legacy tree but missing from `v2/legacy_owned_runtime`.
   - `/home/wali/Desktop/AI BOT/tools/health.py` exists, SHA256 `5e535062b387a501e9c266d0b45681497bd3bf084e40606594223eb2da445dce`, but `v2/legacy_owned_runtime/tools/health.py` is missing.
   - `/home/wali/Desktop/AI BOT/ingest/technical_analysis.py` exists, SHA256 `909437e7e77bcf6a03371c546b074a20e7a216bcd72b13ba783dcd78154dbee0`, but no V2-owned copy is present.
   - `/home/wali/Desktop/AI BOT/monitoring/oom_monitor.py` exists, SHA256 `6fdf878ea8cfbfef7b97c8832ca9a34479763eb42936d2c5a770fab8a4041d57`, but no V2-owned monitoring package is present.
   - `/home/wali/Desktop/AI BOT/monitoring/deep_troubleshooter.py` exists, SHA256 `b293e876155af5af923a9aa2e0c8ece84e0d87e58a37028ee95ebc0f5a364271`, but no V2-owned monitoring package is present.
   - `/home/wali/Desktop/AI BOT/monitoring/live_system_auditor.py` exists, SHA256 `1a72674aab6c2cc14d2915f5dea8e975ca03a89adaebfc7fd0542ddf511cadd4`, but no V2-owned monitoring package is present.
   - `/home/wali/Desktop/AI BOT/monitoring/regression_alarms.py` exists, SHA256 `1bceec7b6756cdda877bf600d0671cdafb008bcfaaf80166c5a457271e8079aa`, but no V2-owned monitoring package is present.

3. Dependency closure still has unresolved local imports.
   - Rerun command: `PYTHONPATH="$PWD" .venv/bin/python -m v2.backend.app.cli.zero_miss_dependency_closure`
   - Result: `py_files=253 unresolved_local=1 external=23 parse_errors=0`
   - Unresolved local import: `tools`

4. Strict smoke still fails and does not hide the missing imports.
   - `v2_owned_ingestors`: `smoke_pass=false`, unresolved `ingest.live_technical_analysis` because `ingest.technical_analysis` is missing.
   - `v2_owned_monitoring`: `smoke_pass=false`, unresolved `monitoring.oom_monitor`, `monitoring.deep_troubleshooter`, `monitoring.live_system_auditor`, and `monitoring.regression_alarms`.
   - `v2_owned_trainer`: now passes after `schedule` is present in the V2 virtualenv.
   - `v2_owned_feature_pipeline`, `v2_owned_orchestrator`, and `v2_owned_trade_management`: pass strict smoke.

5. Native algorithmic core remains outside this remediation.
   - The remediation explicitly says it is not a native algorithmic-core implementation.
   - Legacy shutdown therefore remains blocked independently of the source/import remediation status.

## Passing Checks

- `schedule` is resolved from the V2 virtualenv.
- Config matrix contains `1,917` records with `blocked_unmapped_count=0`; this closes the prior generic `OPERATOR_DECISION_REQUIRED` config state for this review gate, though a per-key V2 receiver registry remains follow-up work.
- Full `v2/legacy_owned_runtime` py_compile passes.
- Focused zero-miss tests pass: `16 passed`.
- JSON validation for remediation payloads passes.
- Old Redis write scan found only guarded V2 namespace-adapter write methods; adapter tests still enforce old-key rejection.
- Exchange mutation scan found no reachable mutation calls in the reviewed V2/backend remediation scope.
- Safety values are stable: `live_gate=blocked_human_only`, `live_symbols=[]`, and all live/canary/shutdown/Redis-trim approvals are false.
- Frontend remediation payload shows NO-GO and does not hide the blockers.

## Required Next Fix

Copy or classify the safe legacy sources now proven present:

- `tools/health.py`
- `ingest/technical_analysis.py`
- `monitoring/oom_monitor.py`
- `monitoring/deep_troubleshooter.py`
- `monitoring/live_system_auditor.py`
- `monitoring/regression_alarms.py`

Then rerun dependency closure, py_compile, strict smokes, JSON validation, old Redis/exchange scans, and frontend truth sync. Do not mark remediation PASS until `unresolved_local_imports=0`, ingestor smoke passes, monitoring smoke passes, and the frontend still shows live/shutdown blocked.
