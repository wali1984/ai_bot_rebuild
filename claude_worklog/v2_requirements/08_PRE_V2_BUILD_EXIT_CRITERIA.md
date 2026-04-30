# 08 Pre-V2 Build Exit Criteria

## Exit criteria before any V2 build
All criteria must be satisfied:

1. ID lineage criteria
- `feature_snapshot_id`, `prediction_id`, `signal_id`, `decision_id`, `risk_decision_id`, `execution_intent_id` are implemented and linked end-to-end.

2. Explainability criteria
- confidence explainability block present with required positive/negative feature contributors and source freshness flags.

3. Redis safety criteria
- memory ratio below critical threshold with validated retention/offload policy in effect.

4. Heartbeat criteria
- heartbeat schema/type compliance validated; no WRONGTYPE ambiguity.

5. Revalidation criteria
- full read-only revalidation cycle passes all mandatory checks.

6. Governance criteria
- additive-only compatibility confirmed; no legacy key deletions introduced.

## Decision rule
If any criterion fails, status remains NO-GO.

PRE_V2_BUILD_REMEDIATION_REQUIRED
