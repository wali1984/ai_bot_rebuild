# Codex Review: V2 Model Path Decision And Native Edge-Proof Gate

Generated: `2026-05-23T02:23:33Z`

GO/NO-GO: `V2_MODEL_PATH_DECISION_CODEX_PASS_NATIVE_EDGE_PROOF`

## Decision

Codex passes the model-path decision with the V2-native edge-proof path as the primary next gate. The packet is now honest about the current observation state, the exhausted exact-source remaining-dim queue, legacy-parity blockers, operator decisions, and recovery proof requirements.

This review does not approve live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, production equivalence, external feed adoption, automatic Symbol Universe adoption, or legacy shutdown.

## Fixes Applied

Codex refreshed the remaining-dim classifier and corrected stale model-path artifacts:

- SOLUSDT is now reflected as `224 / 1687`, matching the live full-observation payload.
- `V2_BUILDABLE_NOW` is now `0`, matching the refreshed queue.
- `V2_LANE_EXISTS_PAYLOAD_ABSENT` is now `21`.
- legacy V3 extra share is corrected to `76.6%` of current missing dims, while remaining `67.7%` of the aggregate target.
- wording that could imply a formal paper edge gate needs no operator action was tightened: spec/evaluator authoring may proceed, but formal edge certification, canary, and live remain operator-gated.

No legacy path was modified. No old Redis key was written. No exchange mutation or approval marker was created.

## Runtime And Observation State

Runtime evidence reviewed:

- Redis reachable: PASS.
- `v2:*` namespace non-empty: PASS.
- trainer, liquidation WSS, and position-history heartbeats present: PASS.
- continuous remediation governor marker: `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`.
- `live_gate=blocked_human_only`.
- `live_symbols=[]`.

Current full-observation state:

| Symbol | Generated | Missing | State |
| --- | ---: | ---: | --- |
| `BTCUSDT` | `224` | `1687` | `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS` |
| `ETHUSDT` | `224` | `1687` | `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS` |
| `SOLUSDT` | `224` | `1687` | `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS` |

The builder remains partial:

- `zero_filled_field_count=0`
- `no_zero_fill_for_unknown_fields=true`
- `checkpoint_compatibility_claimed=false`
- `policy_architecture_parity_claimed=false`
- `FULL_OBSERVATION_BUILDER_COMPLETE` is not claimed

The refreshed remaining-dim queue reconciles to `5733`, with `V2_BUILDABLE_NOW=0`. Remaining blockers are explicit: legacy V3 extra fields, not-required reserved fields, position-dependent fields, external token/onchain sources, CCXT OHLCV operator decision, event-dependent liquidation slots, and payload-absent V2 lanes.

## Path Decision

Codex agrees with the packet's recommendation:

- primary path: `v2_native_compact_to_expanded_model`
- secondary path: legacy-parity comparator preservation only

The V2-native path is concrete and testable. It starts with training-spec and evaluator work against V2-owned paper/shadow evidence and requires measured after-cost paper edge before any canary/live discussion.

The legacy-parity path remains blocked by explicit gates:

- policy architecture gate
- checkpoint artifact / checkpoint deserialization gate
- external token/onchain/CCXT source decisions
- event-dependent liquidation evidence
- open-position-dependent evidence
- legacy V3 extra fields with no V2-native source

Dashboards, report center readiness, and controller readiness are not counted as model readiness or production readiness.

## Safety

Codex verified:

- recovery plan requires paper edge before live
- capital recovery gate does not approve live
- no live/canary/shutdown/Redis-trim approval exists
- no checkpoint compatibility claim exists
- no policy architecture parity claim exists
- no dashboards are treated as readiness
- operator decisions are explicit
- next tasks are automatable and measurable
- no old Redis write path appears in the reviewed packet
- no exchange mutation appears in the reviewed packet
- `live_gate=blocked_human_only`
- `live_symbols=[]`

## Validation

- Remaining-dim classifier refresh: PASS.
- Model-path JSON validation: PASS.
- Full-observation payload inspection: PASS.
- Runtime heartbeat / Redis read-only checks: PASS.
- Report text stale-count scan: PASS, no remaining `~3`, `5074`, or `215 SOL` stale references.
- Secret scan: PASS.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.

## Final Decision

`V2_MODEL_PATH_DECISION_CODEX_PASS_NATIVE_EDGE_PROOF`
