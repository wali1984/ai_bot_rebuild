# 2E1D Test Plan Final Count Addendum

## Canonical count

The canonical authored service test count for 2E1D is 34.

## Rationale

`113_PHASE_2E1D_SERVICE_COMPOSITION_TEST_PLAN.md` listed 34 candidate service test names, then instructed the implementation task to resolve the final count by either consolidating or dropping cases. The implementation report in `116_2E1D_SERVICE_COMPOSITION_IMPLEMENTATION_REPORT.md` is the authoritative final count source for review, and it enumerates 34 authored service test files.

The two files that made the implemented count 34 instead of 32 are not surplus coverage:

- `test_evaluate_appends_proposal_observation_to_proposal_history.py` is the proposal-stream counterpart to prediction-history append coverage.
- `test_evaluate_skips_streams_with_none_latest_id.py` covers the no-latest-id branch without needing live Redis access or service-source changes.

Keeping both preserves one deterministic assertion per authored test file, keeps the forbidden-token guard complete, and matches the actual passing implementation evidence in report 116.

## Final service test inventory

The 34 canonical authored service tests are every `test_*.py` file directly under `v2/backend/tests/unit/services/trainer_parity/` as listed by report 116 and guarded by `test_service_milestone_forbidden_tokens.py`.
