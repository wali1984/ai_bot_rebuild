# Parallel Read-Only Review — Phase 2G.A Risk Gateway Domain Codex Pass

Verdict: review completed; source should remain accepted only as the narrow 2G.A value-object slice. It is not, by itself, a complete paper/backtest MVP risk-gateway handoff.

## Review Posture

- Read-only review only.
- No source patching.
- No Redis writes.
- No live service restart.
- No order placement or cancellation.
- No live trading enablement.
- The unrelated current dirty worktree entry means the prior clean-worktree evidence is stale for present-state claims.

## Findings

1. Blocking-before-MVP-handoff: the risk decision value object carries `risk_decision_id`, `decision_id`, `prediction_id`, and `feature_snapshot_id`, but not `signal_id`.
   The architecture and API lineage shape require the full upstream chain through `signal_id`. Paper execution ledger handoff will either need `signal_id` added to the risk decision handoff contract or a deterministic, tested resolver that reconstructs it from `decision_id` before paper intent creation. Without that, missing-signal attribution cannot be blocked or explained at the risk-gateway boundary.

2. Blocking-before-MVP-handoff: the 2G.A domain does not encode policy-bundle identity, policy check results, stale-signal state, missing attribution state, confidence availability, stop-policy status, duplicate execution status, margin/leverage status, loss gates, kill-switch status, reduce-only status, or position-sizing outputs.
   This is acceptable for the intentionally narrow value-object subphase, but 2G.B/2G.C must not treat the domain PASS as evidence that the risk gateway itself is MVP-complete.

3. Handoff mismatch risk: the domain action taxonomy uses `allow` and `deny`, while the current wire schema vocabulary uses `allow` and `block`.
   This can be handled by an assembler or adapter, but it needs an explicit tested mapping so deny reasons do not drift from API block reasons or paper ledger blocked-intent explanations.

4. Explainability gap: reason codes are deterministic and useful, but the value object does not carry an explainability payload, top driver context, feature freshness detail, confidence, worker-health evidence, policy check list, or lineage gap reason.
   Downstream layers must attach these fields before GUI, audit, or paper/backtest replay views can explain why a decision was allowed or blocked.

5. Stale evidence: the existing Codex review claimed a clean worktree at dispatch time and reported prior test runs. The present review observed a dirty worktree entry outside the reviewed source surface, so clean-worktree claims from the earlier report are no longer current. I did not rerun pytest because this task was explicitly read-only and pytest can update local cache or bytecode artifacts.

6. Legacy evidence weakness: the legacy review states that relevant legacy audit material was mostly stubs and that no legacy file bodies were read. That is acceptable for a new value object, but weak evidence for claiming full behavioral parity with legacy signal-to-execution failures.

## Compatibility Assessment

- Paper/backtest MVP compatibility: conditionally compatible only as a typed risk-decision nucleus. Not complete until full lineage, policy evaluation output, block reason mapping, and paper-ledger handoff tests are added.
- Risk-gateway handoff completeness: incomplete for downstream paper execution unless `signal_id` and policy/audit payloads are supplied by a later deterministic layer.
- Lineage and explainability: partial lineage only; explainability is reason-code level, not full feature-to-action explanation.
- Safety: the value object remains non-live and enforces `live_blocked is True`; no I/O or exchange behavior was observed in the reviewed source.
- Scope control: no evidence that 2G.A drifted into services, adapters, execution, FastAPI, Redis, or live trading behavior.

## Test-Hardening Recommendations

- Add 2G.B/2G.C contract tests proving full lineage propagation includes `signal_id`.
- Add adapter tests proving domain `deny` maps deterministically to API/paper `block`.
- Add policy-output tests requiring policy bundle id, ordered policy checks, stale/missing attribution checks, and human-readable block explanation.
- Add property or matrix tests for boundary identifiers, unknown reason codes, and deny/default combinations.
- Add a read-only verification mode that disables pytest cache and bytecode writes before future parallel reviews rely on fresh test evidence.
- Add stale-evidence checks that fail review if prior clean-worktree or test evidence is reused after new dirty work appears.

## Go/No-Go Recommendation

CODEX_PARALLEL_READONLY_REVIEW_READY_WITH_MVP_HANDOFF_BLOCKERS
