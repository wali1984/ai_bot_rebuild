# Codex Review — V2 Risk Gateway Legacy Action Parity Tests

Verdict: FAIL

Findings:

1. BLOCKER — The required parity tests were not added. The task scope requires non-skipped V2 tests for nine legacy gates and says tests must invoke real V2 gate functions (`REPORT.md:12-26`), but the emitted status records `tests_added_count: 0` and all required V2 callables absent (`STATUS.json:9-20`). The current V2 service still only branches over `open_long`, `open_short`, `hold`, and `abstain` (`v2/backend/app/services/risk_gateway/service.py:25-79`), while the domain allowlist only contains the existing five reason codes (`v2/backend/app/domain/risk_gateway/record.py:23-30`). Current readiness still lists `RISK_GATEWAY_LEGACY_PARITY_TESTS_MISSING` (`operator_dashboard_payload.json:25-30`). This fails the requested shutdown-readiness gate because the legacy action-path behavior remains untested in V2.

2. BLOCKER — Required SHA evidence is incomplete for `adaptive_microstructure_toxicity`. The baseline and mapping cite the SHA for `risk/microstructure_toxicity.py`, but they name `risk/adaptive_gate.py` as the paired consumer without recording its SHA (`LEGACY_BASELINE_ANALYSIS.md:114-125`, `legacy_behavior_mapping.json:146-153`). The source manifest contains the missing `risk/adaptive_gate.py` SHA `a5057ea4ad4542881a6ebf14b9d789cbeed7873fc763c9d74d06c7c781674bce` (`full_runtime_copied_source_manifest.json:1923,1925`). This violates the required SHA evidence standard.

Safety checks:

- No silent pass observed: Claude explicitly marked the task blocked/no-go for test expansion (`REPORT.md:153-157`, `STATUS.json:41-43`).
- Live gate remains `blocked_human_only`; live symbols remain empty; final and Redis trim approval tokens remain absent (`STATUS.json:5-8`, `current_recommendation.json:4-7`, `operator_dashboard_payload.json:4-6,155-157`).
- Current payloads report old Redis writes absent, exchange actions absent, leverage changes absent, and margin mode changes absent (`operator_dashboard_payload.json:81,170`, `shutdown_readiness_state.json:705-718`).
- Read-only grep review found no Redis writer or exchange/leverage/margin mutation calls in the relevant V2 risk gateway source/tests.
- Tests were not run during this review to preserve read-only shutdown-readiness constraints.
