# 12B API Lineage Enforcement Closure

## Gap statement
Prior to this update, `claude_worklog/v2_architecture/05_API_CONTRACTS.md` named lineage carriage in §1.3 only as a one-paragraph requirement. It did not define:
- the canonical wire shape of the `lineage` block on every lineage-bearing payload,
- which IDs must be non-null on which stage (prediction vs signal vs orchestrator vs risk vs execution),
- the dedicated error classes raised when lineage is malformed, missing, unresolved, cross-symbol, chain-broken, duplicated, or mutated,
- per-endpoint enforcement rules for `/v1/predictions/*`, `/v1/signals/*`, `/v1/orchestrator/decisions/*`, `/v1/risk/decisions/*`, and `/v1/executions/*`,
- mappable test vectors that V2 implementations must pass before claiming the chain is enforced.

The database side of the chain was closed in `12A_DATABASE_LINEAGE_CLOSURE.md`, but the API contract had no symmetric enforcement, so an application-layer bug could let a request reach the DB before the integrity error fired — losing the structured error class and operator-readable diagnostics.

## What was added

1. **Canonical lineage block on the wire (§1.3.1).** Every lineage-bearing request and response carries a seven-key `lineage` object: the six chain IDs plus `lineage_gap_reason`. Upstream IDs MUST be non-null for the stage; downstream IDs MUST be explicit `null` (omission is a malformed payload). `lineage_gap_reason` is an enum (`upstream_missing | downstream_not_yet_emitted | ingest_pre_attribution | replay_partial`).
2. **Stage-by-stage required-ID matrix (§1.3.2).** Feature-snapshot ingest requires only `feature_snapshot_id`. Prediction ingest requires `feature_snapshot_id`+`prediction_id`. Signal ingest requires through `signal_id`. Decision ingest requires through `decision_id`. Risk requires through `decision_id`+`risk_decision_id`. Execution intent requires the full upstream chain through `risk_decision_id`. Paper trade ack carries the full chain.
3. **Lineage error classes added to the catalog (§3.2/§3.3).** Seven new classes:
   - `lineage.malformed` (400) — block missing/extra/typed wrong/downstream slot omitted.
   - `lineage.missing_attribution` (422) — required upstream ID null with no valid gap reason.
   - `lineage.parent_not_found` (422) — non-null upstream ID does not resolve.
   - `lineage.cross_symbol` (422) — child symbol/timeframe disagrees with resolved parent.
   - `lineage.chain_break` (422) — two upstream IDs disagree about ancestry.
   - `lineage.immutable_violation` (409) — mutation on an immutable chain ID.
   - `lineage.duplicate_child` (409) — two children claim the same single-parent slot inside the de-dup window.
4. **Database integrity error mapping (§3.4).** When the DB integrity error is the actual gate (because the application validator was bypassed), the API returns the same lineage class. NOT NULL FK → `lineage.missing_attribution`; FK RESTRICT → `lineage.parent_not_found`; allow/block CHECK → `validation.policy`; execution-intent block trigger → `risk.gateway_block`. The class catalog is therefore consistent regardless of which layer rejects the request.
5. **Enforcement order made explicit (§2.3).** Lineage validation runs after schema validation but before live-block, idempotency, and concurrency checks, so the response class is reproducible from the request.
6. **Endpoint-level enforcement rules (§9).** Each lineage-bearing group has a normative subsection:
   - §9.1 lists the nine common pre-handler validators (shape, type, stage-required, gap-reason, parent-existence, cross-symbol, chain-coherence, immutability, single-parent uniqueness).
   - §9.2 covers `/v1/feature_snapshots/*` (chain root).
   - §9.3 covers `/v1/predictions/*` — requires `feature_snapshot_id`, mirrors DB NOT NULL on `model_version`/`checkpoint`/`raw_output_json`, and embeds the resolved snapshot in `/explain`.
   - §9.4 covers `/v1/signals/*` — requires `prediction_id`, enforces `action` enum and `confidence` range, mirrors DB NOT NULL on `reason_json`, and applies single-parent de-dup per `(prediction_id, publish_window_ms)`.
   - §9.5 covers `/v1/orchestrator/decisions/*` — requires `signal_id`, enforces `decision_action` enum, mirrors DB NOT NULL on `policy_trace_json`.
   - §9.6 covers `/v1/risk/decisions/*` — internal-scoped ingest, enforces `allow_block` enum + the `(allow ↔ block_reason)` conditional, mirrors DB NOT NULL on `policy_checks_json`.
   - §9.7 covers `/v1/executions/*` — full upstream chain required; resolved `risk_decisions.allow_block` MUST be `'allow'` (else `risk.gateway_block`); live mode triggers §7 live-block AFTER lineage is validated.
   - §9.8 covers `/v1/positions/*` and `/v1/audit/*` as chain-reference (not chain-member) surfaces with the same filter requirements.
   - §9.9 forbids half-populated lineage blocks on routes outside the lineage-bearing groups.
7. **Lineage filters elevated to first-class (§6).** Every event feed accepts `?filter[feature_snapshot_id]=`, `?filter[prediction_id]=`, `?filter[signal_id]=`, `?filter[decision_id]=`, `?filter[risk_decision_id]=`, `?filter[execution_intent_id]=`, hitting the indexes declared in `03_DATABASE_SCHEMA.md`.
8. **Idempotency hash includes lineage (§4).** Lineage IDs are part of `body_hash` so a replayed ingest under the same idempotency key cannot smuggle in a different chain.
9. **Scaffoldable test vectors (§13).** 30+ accept/reject vectors grouped by stage, each with `name`, `route`, `request`, `preconditions`, `expected_status`, and `expected_class`. The negative-vector index (§13.8) shows that every `lineage.*` class has at least one rejecting vector and every CHECK-class business invariant has at least one rejecting vector. §13.7 covers read-side assertions on lineage carriage. §13.9 specifies how a future V2 build task materializes these as fixtures.

## Why this closes the gap

- The lineage chain has a single, normative wire shape, so any request or response can be programmatically validated against it. Implementations cannot drift to per-route ad-hoc shapes.
- Every required ID at every stage is enumerated. There is no ambiguity about whether `signal_id` is required at prediction ingest or whether `risk_decision_id` is required at execution intent submission.
- Every class of lineage failure has a dedicated error class with stable HTTP status and `details` shape. Operators and downstream tools (Audit Ledger, Signal Explainability, Monitor Center) can dispatch on class without parsing prose messages.
- The endpoint-level rules in §9 mirror the database constraints in `03_DATABASE_SCHEMA.md` 1:1, so application validation and database integrity always agree on what is rejectable. The §3.4 mapping makes the agreement explicit even when the DB is the gate.
- The test vectors in §13 give a concrete, language-agnostic acceptance criterion. A V2 build task that fails any vector cannot claim the gap is closed.
- Live mutation routes still default-deny per `CLAUDE.md`. Lineage validation runs before the live-block check, so a malformed live-execution request gets the precise lineage class instead of a generic `live_blocked`.

## Verification pointers
- File updated: `claude_worklog/v2_architecture/05_API_CONTRACTS.md` — see §1.3 (lineage carriage), §2.3 (enforcement order), §3.2/§3.3 (error classes), §3.4 (DB error mapping), §6 (lineage filters), §8 (lineage-bearing column), §9 (per-endpoint enforcement), §13 (test vectors).
- File created: `claude_worklog/v2_architecture_remediation/12B_API_LINEAGE_ENFORCEMENT_CLOSURE.md` (this file).
- Source remediation file `04_API_CONTRACT_REMEDIATION.md` remains the schema-delta authority for the concrete payload shapes (`FeatureSnapshot`, `PredictionEvent`, `SignalEvent`, `OrchestratorDecision`, `RiskDecision`, `IntentRequest`, `ExecutionIntent`, etc.); §10 of the updated `05_API_CONTRACTS.md` references it.
- Database lineage closure (paired): `claude_worklog/v2_architecture_remediation/12A_DATABASE_LINEAGE_CLOSURE.md`.
- Requirements alignment:
  - `claude_worklog/v2_requirements/01_OBSERVABILITY_AND_ATTRIBUTION_SPEC.md` "Required record envelope" — every stage emits the six IDs.
  - `claude_worklog/v2_requirements/03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md` integrity rules — no child ID without parent ID, parent IDs immutable, cross-symbol invalid, missing lineage is a hard validation failure.
- Task spec: `claude_worklog/agent_supervisor/tasks/012b_api_lineage_enforcement.json`.
- Required outputs declared by task spec are both produced:
  - `claude_worklog/v2_architecture/05_API_CONTRACTS.md`
  - `claude_worklog/v2_architecture_remediation/12B_API_LINEAGE_ENFORCEMENT_CLOSURE.md`

## Out of scope
- No V2 code is shipped. Validators, error classes, and test vectors are architecture-text deliverables.
- No Redis writes, no service restarts, no live trader changes, no legacy bot mutation. Live trading remains BLOCKED by default per `CLAUDE.md`.
- The connector / pre-feature ingest surface is explicitly carved out in §9.9 and not given a `lineage` block.

## Status
API lineage architecture gap: CLOSED at the architecture-text level. A future V2 build task must materialize:
- the `lineage` block as a concrete Pydantic/JSON-Schema model,
- the nine pre-handler validators as middleware/dependencies,
- the seven `lineage.*` error classes as exception types mapping to the documented HTTP statuses,
- the §13 test vectors as fixtures + a runner under `v2/tests/`,
- the §3.4 DB integrity-error translator at the SQLAlchemy/SQL boundary.

Any deviation from §1.3, §3.2/§3.3, §9, or §13 reopens this gap.