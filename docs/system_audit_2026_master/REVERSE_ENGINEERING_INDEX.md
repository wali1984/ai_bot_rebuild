# AI Bot V2 reverse-engineering index

**Audit snapshot:** 2026-07-16 reconstruction with coordinated source regression and post-reload runtime reconciliation through 2026-07-18 UTC

**Scope:** source, deployed processes, configuration surfaces, data contracts, temporal lineage, trainer/model, decision and paper/live execution, API, security, persistence, web/mobile clients, operations, recovery, and tests.

**Safety state observed:** non-live; real exchange mutation code exists but the deployed live path is disarmed. This document is not authorization to enable it.

This directory is the canonical documentation set for reconstructing the current system. It deliberately separates three kinds of truth:

1. **Versioned design** — what the tracked source and unit files say.
2. **Deployed reality** — what was installed and running on the audited workstation.
3. **Behavioral confidence** — what static analysis, tests, or live read-only evidence actually proves.

Do not collapse those categories. A source file is not proof that its service is installed; a running service is not proof that its source is committed; a Redis status payload is not proof that the operation it describes succeeded.

## Canonical human documents

| Document | Use |
|---|---|
| [AI_BOT_V2_FULL_REBUILD_MASTER_AUDIT_REPORT.md](AI_BOT_V2_FULL_REBUILD_MASTER_AUDIT_REPORT.md) | 2026-07-16 rebuild baseline plus its 2026-07-17 reconciliation pointer and current NO-GO decision; use the dated adaptive document for current-source deltas. |
| [AI_BOT_V2_MASTER_OPERATOR_MANUAL.md](AI_BOT_V2_MASTER_OPERATOR_MANUAL.md) | Safe observation, triage, recovery, restart constraints, and incident procedures. |
| [V2_SYSTEM_TECHNICAL_REFERENCE.md](../../v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md) | Code-level architecture, contracts, entrypoints, state transitions, and implementation semantics. |
| [RUNTIME_PROCESS_AND_DEPLOYMENT.md](components/RUNTIME_PROCESS_AND_DEPLOYMENT.md) | Installed-versus-versioned process topology, systemd, namespaces, and startup behavior. |
| [DATA_TEMPORAL_LINEAGE_AND_FEATURES.md](components/DATA_TEMPORAL_LINEAGE_AND_FEATURES.md) | Provider inputs, timestamps, candle finality, feature assembly, masks, point-in-time gaps, and the historical 477/1,908 versus intended current 446/1,784 feature-ABI generations. |
| [TRAINER_PPO_MASA_REPLAY_AND_CHECKPOINTS.md](components/TRAINER_PPO_MASA_REPLAY_AND_CHECKPOINTS.md) | Historical 477/1,908 deployment generation versus intended current 446/1,784 source contract, historical 374-test ABI reconciliation plus the current 331-test trainer/PIT lane, remaining checkpoint/replay migration debt, training objectives, purged validation/promotion, behavior-policy/PPO truth, replay labels, final-holdout gap, publishing, and persistence. |
| [DECISION_RISK_PAPER_AND_LIVE_EXECUTION.md](components/DECISION_RISK_PAPER_AND_LIVE_EXECUTION.md) | Prediction-to-orchestrator-to-risk-to-paper flow, actual admission semantics, position lifecycle, and dormant live mutation paths. |
| [API_AUTH_STORAGE_WEB_AND_MOBILE.md](components/API_AUTH_STORAGE_WEB_AND_MOBILE.md) | FastAPI, middleware, authentication, Redis/SQLite/file state, React, SwiftUI, and exposure boundaries. |
| [CONFIG_KEYS_CONTRACTS_AND_CHANGE_IMPACT.md](components/CONFIG_KEYS_CONTRACTS_AND_CHANGE_IMPACT.md) | How to locate every config key, Redis pattern, payload field, route, caller, importer, and affected test. |
| [REBUILD_BLUEPRINT.md](REBUILD_BLUEPRINT.md) | Minimum reproducible specification and ordered reconstruction plan. |
| [CURRENT_FINDINGS_AND_RISK_REGISTER.md](CURRENT_FINDINGS_AND_RISK_REGISTER.md) | Evidence-linked defect and drift register. |
| [ADAPTIVE_END_TO_END_CONTROL_AND_ACCOUNTING_2026-07-17.md](ADAPTIVE_END_TO_END_CONTROL_AND_ACCOUNTING_2026-07-17.md) | Dated trainer-to-feedback map, Redis ownership, adaptive/safety boundary, dynamic envelope, 47-clock per-candidate allocation PIT contract, frozen entry/preemptive input hashes, strict A+ regime/HTF/tape clock semantics, post-step notional/margin identity, authenticated account/environment bracket evidence, normalized nested/raw/flat lifecycle provenance, cumulative whole-position maintenance equations, two-phase halted-probe tokens, outcome-memory/hedge hazards, certification semantics, and function-level impact matrix. |
| [OPERATOR_VALIDATION_AND_MONITORING_RUNBOOK_2026-07-17.md](OPERATOR_VALIDATION_AND_MONITORING_RUNBOOK_2026-07-17.md) | Safe paper-only commands, expected fail-closed states, A+ context-clock, frozen entry/preemptive, allocation-PIT and post-step capital receipt inspection, leverage/bracket/margin/probe/hedge checks, restart boundary, monitoring window, and repair exit criteria. |
| [COMMAND_LEDGER_2026-07-17.md](COMMAND_LEDGER_2026-07-17.md) | Exact commands and mutation boundary for the dated audit/repair turn; credential-bearing diagnostic output is intentionally excluded. |
| [VALIDATION_AND_LIMITATIONS_2026-07-16.md](VALIDATION_AND_LIMITATIONS_2026-07-16.md) | Exact scoped test outcomes, snapshot integrity, secret/document checks, and deliberate safety boundaries. |
| [HISTORICAL_ARTIFACT_CLASSIFICATION.md](HISTORICAL_ARTIFACT_CLASSIFICATION.md) | Prevents legacy JSON/JSONL/inventory/graph fields from being consumed as current truth. |
| [COMMANDS_RUN.md](COMMANDS_RUN.md) | Exact audit/build/test tool ledger, including the complete verbatim local session records. |

The older component audits and root JSON/JSONL/inventory/graph artifacts in this directory are retained as historical pre-2026-07-16 evidence. Their current-sounding fields are not authority. Use `HISTORICAL_ARTIFACT_CLASSIFICATION.md` before consuming any legacy machine artifact. Where old artifacts conflict with this index or the 2026-07-16 documents, the later evidence wins. Values such as process counts, key counts, PnL, service state, and current Git commit are snapshots and must be refreshed before an operational decision.

## 2026-07-18 low-level reconciliation map

The five canonical documents updated at this cut now distinguish source proof, deployed evidence and unresolved authority. Use these joins when tracing a proposed change:

| Question | Source/function path | Key/schema/data joins | Canonical document |
|---|---|---|---|
| What can enter the accepted list? | `v2_trade_management_paper_loop.py::_paper_append_accepted_with_halted_probe_finalization` → `_paper_final_admission_point_in_time_contract` → `_paper_revocable_control_commit_revalidation` | `paper_cycle_reservation_commit_v1`, `paper_revocable_control_commit_revalidation_v1`, `paper_final_admission_contract_v3`, final receipt/bound/projection hashes | [V2_SYSTEM_TECHNICAL_REFERENCE.md](../../v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md#0-2026-07-18-paper-finality-and-authority-addendum) |
| How is same-cycle capital prevented from being reused? | `cycle_reservation.py::{build_cycle_reservation_snapshot,build_candidate_commit_receipt,validate_intrinsic_candidate_commit_receipt}` | dynamic base/precycle/envelope hashes; notional, symbol, margin, stop-loss/drawdown; exact prior receipt/allocation order | [MASTER_SYSTEM_DOC.md](../MASTER_SYSTEM_DOC.md#final-admission-reservation-and-control-authority-reconciliation-2026-07-18-utc) and the technical reference |
| How is an existing open position valued? | `_paper_accepted_fill_proof_source` → `_paper_precycle_current_mark_exposure_snapshot` → `_paper_persisted_admission_rejection_reasons` | `v2:paper:accepted_fills`; stable source-fill IDs; current mark source hash/times; equal positive max-loss aliases; v3/cycle/revocable hashes | Technical reference sections 0.3/0.7; [CURRENT_FINDINGS_AND_RISK_REGISTER.md](CURRENT_FINDINGS_AND_RISK_REGISTER.md#re-039--paper-allocations-have-no-transactional-reserved-margin-ledger) |
| Who owns current mark/index evidence? | `v2_binance_mark_price_wss_seeder.py`, its systemd unit, `v2_binance_public_metadata_ingestor.py`, `v2_native_ingestors_live_loop.py` → `_read_v2_mark_index_evidence` | preferred `v2:market:mark_price:<SYMBOL>` then funding/prices; public `!markPrice@arr@1s`, TTL 180, 600-message reconnect/universe refresh, no REST/account/order/margin mutation; source event/generated/available/cadence/observed clocks; cache age <=120s independent of TTL; `REDIS_KEY_OUTER_SELECTED_PATH_PAYLOAD_AND_FIELD_MAP_SHA256_V2`; current divergence/precycle mark consumers | Technical reference 0.4.1; risk RE-054 |
| Which market evidence may size a candidate? | `_read_v2_microstructure_trust`; `_derive_allocator_liquidity_score` / `_derive_allocator_regime_score` / `_derive_candidate_correlation_contexts` → `_build_allocation_input` | exact trust schema/identity/clocks/minimum/action (payload expiry/consumer TTL proof absent); complete depth+spread or explicit current score; intent-owned regime; strict-clock explicit-finality/available 1m returns for every existing and same-cycle pair; child `paper_correlation_accepted_source_material_v2` / `SOURCE_KEY_DECISION_TIME_ACCEPTED_CLOSE_AVAILABLE_FINALITY_AND_REJECT_COUNTS_CANONICAL_SHA256_V2`; aggregate `paper_correlation_aggregate_source_material_v1` / `DECISION_CANDIDATE_OPEN_SYMBOLS_AND_SORTED_CHILD_SOURCE_MATERIAL_CANONICAL_SHA256_V1`; pair counts/status; `allocator_market_evidence_status`; risk veto | Technical reference 0.4; risk RE-050/RE-040 |
| Which controls can revoke a previously passing entry? | `_paper_revocable_control_source_materials` / `_paper_revocable_control_commit_revalidation` | guardian, entry freeze, portfolio, canonical tuning, paper session, positions-or-ledger, closed trades, process owner; TTL, exact hash equality, session identity and tuning semantics at reread/commit clocks | [AI_BOT_V2_MASTER_OPERATOR_MANUAL.md](AI_BOT_V2_MASTER_OPERATOR_MANUAL.md#0-current-paper-admission-operating-contract); RE-051 |
| Who owns adaptive tuning? | `cli/v2_adaptive_gate_tuner.py::{learn_market_regime,run_once}` canonical publisher; `adaptive_gate_tuning_rejection_reasons` + paper `_paper_adaptive_tuning_semantic_validation` consumer; `services/adaptive_gate_tuning/runtime_tuner.py` diagnostic shadow; lifecycle truthful outcomes | canonical state/policy v4 + publication receipt; exact BTC/ETH/SOL closed-1m keys; 20 final rows/source, `close<=event<=available<=cutoff`, three 60-second cadences; empirical q25/median/q75/percentile and bounded factor 0.70–1.50; `paper_adaptive_tuning_semantic_validation_v1`; P0 blocker; shadow non-authoritative; `PAPER_CLOSE_OUTCOME_AVAILABILITY_V1` | Technical reference 0.5; risk RE-053 |
| How is adaptive-sizing status compacted, and what remains blocked? | `_paper_adaptive_sizing_runtime_status` → bounded adaptive/persistent/exploration projections; top-level status; `write_payload`; OOS/Guardian | controlled one-shot exit0/69.85s/4.70GiB/zero swap/597-0-597; canonical 4,160,870B; adaptive 622/622 hashable and Guardian-valid; persistent 132/132 legacy-unhashable FAIL_CLOSED; exploration all blocked; service held and repeated resident burn-in pending | Technical reference 0.4.2; risk RE-055 |
| Why are seven research/trainer/replay services held? | Redis/resource audit; `run_counterfactual_sweep`; Guardian SQLite publisher/outbox/migration + archive consumer; edge-replay counterfactual archive/hot set; trainer auto-promote/guard timers; user-systemd holds | Redis ~25.49GiB/allkeys-lru/no AOF; Guardian TTL−1 list 6,054,941/~6.23GB and counterfactual TTL−1 string 536,827,021B; former peaks 6.97–22.94GB plus swap; 4,592,832-config/1.65GiB/zero-swap semantic-NO_GO. Initial retention 62-test draft rejected; corrected source passes 87 (18 consumer): transactional outbox, bounded legacy migration, explicit-cost immutable counterfactual archive, hash/chain/PIT/finality consumer, dirty quarantine, fsynced sink and complete migration/outbox/cursor trim gate. No runtime migration/trim/deployment; holds/timer stops remain | Technical reference 0.4.5; risk RE-060 |
| How was microstructure/supervisor log growth bounded? | monitor `_loop_log_payload`/`main`; monitor/logrotate units; supervisor `NON_DURABLE_POLL_EVENTS`/`append_event` | Monitor full authoritative 149-symbol rows remain Redis/status; stdout compacted from 679,324B/4.62s to 949B/4.95s, 13 tests; ~14GB gzip-preserved as ~876MiB. Supervisor 10.9GB log grew ~112KB/10s; source stops appending two stable poll-event types and keeps bounded queue counts/sample, but writer not restarted/deployed and history untouched | Technical reference 0.4.5; risk RE-060 |
| Which trainer import/runtime/checkpoint defects were narrowed? | four installed/versioned units; `checkpoint_retention_status`; `online_learning_runtime_fields`; `build_learning_readiness`; offline wrapper | quoted complete `PYTHONPATH`; validation guard true; child failure propagated; retention v2 scans lifecycle stores, pins active serving/latest candidate/pending-claim artifacts+SQLite files, deletes complete unpinned pairs only and fails closed on unreadable claims; outer runtime schema preserved; cycle PID separated from service liveness; process/CUDA require evidence. Four trainer services held, two timers stopped; no training/checkpoint burn-in | Technical reference 0.5.4; risk RE-018/RE-062/RE-066 |
| Why is the trainer still dead/not ready after source integration? | `runtime.py::run_hybrid_trainer_cycle`; checkpoint lifecycle; `training_state.py`; PPO split | Source now calls separate serving/candidate/rejected stores, startup reconcile, fixed-point claims, optimizer WAL fence, candidate/confidence/serving gates, artifact dispositions, ledger record and verified restore with microsecond decisions/no-expiry receipts. No held integrated cycle ran; sole/latest PPO can remain validation-only. Keep holds until bounded cold-start/restore/reject/promote/crash proof | Technical reference 0.5.5; risk RE-063; operator 5.3/7.4 |
| Where does an exact behavior receipt survive Redis loss? | `durable_behavior_receipt_archive.py`; publisher; paper entry/outcome; trainer ledger | `.local_data/v2_native_trainer/durable_behavior_receipt_archive`; fsynced content-addressed `v2_durable_behavior_receipt_archive_v1`; events `PUBLISHED→ENTRY_ACCEPTED→OUTCOME_FINALIZED→TRAINER_CONSUMED`. Source integrates through OUTCOME; post-ledger TRAINER event is missing, so retention remains required. No GC/backup/bounded-growth proof | Technical reference 0.5.1/0.5.5; risk RE-066; operator 0/5.3 |
| Which adversarial trainer semantics are fixed, and what remains? | receipt/finalized-outcome builders; confidence V2; `_ppo_ineligibility_reason`; full cache digest; checkpoint lifecycle | Current source rejects equal/naive clocks, nonterminal/fractional/arbitrary reward, contradictory gross/costs, optional weight identity, interior-cache mutation, external NPZ paths and unfitted/uncertainty-regressing confidence; main cycle integrates the lifecycle. Configured paper/shadow fee+notional identity is hashed/rederived; actual exchange-account fee authority remains a live-transfer residual. Paper/trainer blockers are runtime burn-in, process-local lane state, deployed old cost schema, scarce-PPO split and static threshold inventory | Technical reference 0.5.1/0.5.3/0.5.5; risk RE-061/RE-064; command ledger 12.11 onward |
| What does the cross-margin surface actually prove? | `v2_portfolio_cascade_guard_loop.py::_paper_margin_inputs` → `cross_margin_liquidation.py::build_portfolio_liquidation_snapshot` | exact symbol join to `paper_account_margin_status.position_margin_rows`; `paper_cascade_margin_join_v1`; `cross_margin_liquidation_v2`; quantity/mark/leverage aliases and completeness; fail-closed `UNTRUSTED_MARGIN_EVIDENCE`; static shock/beta diagnostics; allocator remains `isolated_paper_simulated` | Technical reference 0.4.3; risk RE-056/RE-040 |
| Is PPO currently receiving on-policy supply? | old paper predicate; current adaptive plan/receipt/cost envelope → durable receipt lifecycle → finalized outcome → exact claim/lifecycle | Runtime no: old generation remains PPO admitted/consumed/clipped 0/0/0 and HALTED. Current source requires exact weight/evidence/symbol/timeframe, strict clocks, embedded adaptive cost, terminal reward/outcome digest, immutable archive/no-expiry Redis receipt and unique ledger disposition. Archive is integrated through OUTCOME but lacks post-ledger TRAINER closure. Deployed cost schema is old and no held integrated cycle ran; deploy/burn-in pending | Technical reference 0.5.1; risk RE-058/RE-066/RE-014 |
| What does trainer confidence mean? | `confidence.py` → directional head → exact economics → calibration → confidence gate → checkpoint | selected LONG/SHORT P(recomputed action/side/price/quantity gross minus exact entry+exit fee/slippage plus signed funding >0); complete versions/provenance/no fallback; purged-fit-only V2 state bound to weights; global/LONG/SHORT paired Brier one-SE and ECE jackknife one-SE non-regression. The main cycle invokes this necessary/non-serving gate; runtime targets/fit/reliability remain zero/unproved | Technical reference 0.5.3; risk RE-061 |
| How does a partially closed position survive restart? | `position_state.py::{reconstruction_envelope,validate_paper_position_reconstruction}`; lifecycle restore/netting; accepted-fill compaction | `PAPER_OPEN_POSITION_RECONSTRUCTION_V1` hashes identity/generation/clocks/qty/entry/source fills/realized PnL and entry fee+slippage conservation; historical netting receipts bind close/generation/fill/side and input=consumed+residual; final-close suppression requires quantity proof; legacy/tampered/incomplete state quarantines. Source 509+16+4 green; runtime migration/restart unproved | Technical reference 17/18; risk RE-065; operator 5.6 |
| How do the approved 75/50/20 ceilings bind leverage? | `symbol_leverage_ceiling` / `_liquidation_safe_max_leverage`; `dynamic_envelope.py`; allocator `_adaptive_leverage_target`; bracket/margin contracts | preserve tiers + 5x ATR; 3x base interpolates toward authorized ceiling only on favorable PIT/realized evidence and contracts otherwise; candidate target is min of Phase-8 recommendation and continuous target inside dynamic/symbol cap; signed authenticated bracket creates integer 1..min(bracket,tier); 223 allocator/Phase-8 + six bracket-selection tests green; runtime credential binding still blocked; G10; isolated-only; negative edge earns no high leverage | Technical reference 0.4.4; risk RE-059/RE-040/RE-049 |
| Who owns executable paper filter metadata? | `v2_direct_orderbook_recorder.py::{_safe_symbol_filter_cache_set,_validated_canonical_symbol_filter_cache_payload,_canonical_symbol_filter_cache_refresh_due}`; consumer `_paper_exchange_filter_snapshot` | exact `v2:exchange:symbol_filters:<SYMBOL>`; `binance_usdm_symbol_filter_cache_v1`; raw/full hashes; fetched/ingested/available/observed; 24-hour TTL and 15-minute refresh | Technical reference 0.6; risk RE-049 |
| Is Ridge +30 bps proven? | `model_edge_recovery_challenger.py`; durable archive; schema/policy v2 | no: 16 source tests; real 200-row probe 0.19s/29,208KB, fee missing145, slippage missing145, latest-unclosed proof missing55, four-hour-purged train/validation/holdout 0/0/0; no model/edge claim | Technical reference 0.5.2; risk RE-057 |
| What remains impossible to claim? | runtime evidence and unresolved blockers | no Redis fence/CAS or canonical-key ACL; retention migration pending; credential binding blocked; negative edge; 132 history rows fail closed; one bounded paper/Guardian run; seven services held/two timers stopped; integrated trainer unburned; old deployed cost schema; runtime PPO 0/0; no compatible calibrated serving checkpoint/high leverage; actual exchange-account fee authority/static thresholds; G11/G12 fail; no A+ chain; live disabled | Master document, operator section 0 and current findings header |

Current source regressions were **533/533 paper-loop** (prior checkpoints 530 and 526), **331 trainer/PIT**, **480 lifecycle/paper-trade-management**, **207 allocator**, **16 adaptive-tuning** (prior checkpoint 15), **72 recorder/integration**, **92 orchestrator/risk**, **99 preemptive/A+**, and **77 portfolio/microstructure** tests. Compact dependents passed **91/91 OOS**, **33/33 Guardian** and **77/77** post-fix preemptive-edge-control; margin/cascade passed **13/13** focused cases. Allocator + adaptive-productivity + Phase-8 passed **323/323**; six authenticated-bracket selections passed with 531 deselected. Ridge passed 16; historical confidence passed 35 focused +66 adjacent +1 refusal; exact on-policy passed 73 combined/16 receipt/5 selected paper/8 collapse/54 full router plus static checks. Final adversarial reruns added 16 receipt and 25 confidence/profitability passes. Confidence V2 then passed 12 calibration/proportional plus 15 selected economics cases, but concurrent checkpoint-SHA integration left the aggregate at 36/39 pending reconciliation. Negative probes still reproduce other trainer P0/P1 gaps. Retention's original 62-test draft was rejected; corrected source passes 87 combined, including 18 focused consumer cases, without runtime migration. None is a deployed/final runtime gate. Lanes overlap and must not be summed. This is source plus bounded one-shot confidence, not trainer readiness, resident-service, accepted-row, market-performance or A+ evidence.

Runtime remains an honest NO-GO: performance is `HALTED_PERFORMANCE` with LCB −47.0423 bps, PF 0.703666, weighted expectancy −7.70099 bps and win rate 0.43478. Paper completed 597/0/597 at 4.70 GiB/zero swap; Guardian completed semantic BLOCKED at ~35 MiB/zero swap but accepted 0 economic rows despite 99,644 PIT-valid coverage observations. Persistent 132-row history stayed FAIL_CLOSED. Margin accounting passed 2/2, but bracket security was `CREDENTIAL_BINDING_NOT_ACCOUNT_SPECIFIC`; no leverage binding/mutation/order occurred. Seven services remain held and two trainer timers are stopped; Redis TTL−1 evidence objects and the 10.9GB growing supervisor log remain pressured. PPO runtime is 0/0; Ridge is 0 rows. WSS per-candidate closure, compatible calibrated checkpoint, retention migration, fencing/ACL, G11/G12 and threshold debt remain open. Live is disabled; A+ and 1000x are not achieved or guaranteed.

## Exhaustive machine atlas

The `atlas/` directory is the function-level navigation layer. It was generated from Git-tracked worktree content at one recorded HEAD, and every tracked input was content-hash revalidated before publication; dirty tracked content is deliberately included. Secret-like files and values are excluded. The expanded JSON catalogs are deterministic local build artifacts and intentionally ignored by Git because they occupy hundreds of megabytes; regenerate them after source changes and validate them against the build manifest.

| Artifact | Cardinality/question |
|---|---|
| [FILE_MODULE_CATALOG.json](atlas/FILE_MODULE_CATALOG.json) | 9,272 tracked paths: hash, bytes, LOC, language, stratum, parse status. |
| [PYTHON_SYMBOL_CATALOG.json](atlas/PYTHON_SYMBOL_CATALOG.json) | 32,272 module/function/class/method records with location, signature, decorators, calls, fields, Redis/config/API and side effects. |
| [TYPESCRIPT_JAVASCRIPT_ATLAS.json](atlas/TYPESCRIPT_JAVASCRIPT_ATLAS.json) | 3,334 symbols plus imports, client routes, contracts, env keys, and calls. |
| [SWIFT_SYMBOL_CONTRACT_CATALOG.json](atlas/SWIFT_SYMBOL_CONTRACT_CATALOG.json) | 693 Swift declarations and client/data-contract references. |
| [PYTHON_IMPORT_GRAPH.json](atlas/PYTHON_IMPORT_GRAPH.json) | 25,389 import edges; 8,708 statically resolved to internal files. |
| [PYTHON_CALL_GRAPH.json](atlas/PYTHON_CALL_GRAPH.json) | 161,112 call references; 38,744 statically resolved to internal symbols. |
| [DATA_CONTRACTS.json](atlas/DATA_CONTRACTS.json) | 1,807 dataclass, TypedDict, Pydantic, TypeScript, and Swift contracts. |
| [DATA_CONTRACT_FIELD_REGISTRY.json](atlas/DATA_CONTRACT_FIELD_REGISTRY.json) | 39,538 field names with declaration/read/write sites. |
| [API_ROUTE_REGISTRY.json](atlas/API_ROUTE_REGISTRY.json) | 905 server definitions and client/reference sites; this is not the same as the current OpenAPI operation count. |
| [CONFIG_ENV_REGISTRY.json](atlas/CONFIG_ENV_REGISTRY.json) | 2,918 environment/static key names, safe defaults, and consumer sites. |
| [REDIS_KEY_USAGE_REGISTRY.json](atlas/REDIS_KEY_USAGE_REGISTRY.json) | 2,040 key patterns and literal/derived read/write sites. |
| [ENTRYPOINT_SERVICE_REGISTRY.json](atlas/ENTRYPOINT_SERVICE_REGISTRY.json) | Python mains, package scripts, shell entrypoints, Make targets, and systemd directives. |
| [EXCHANGE_MUTATION_REFERENCE_REGISTRY.json](atlas/EXCHANGE_MUTATION_REFERENCE_REGISTRY.json) | 37 order/cancel/leverage/margin/transfer-related source references requiring manual review. |
| [CHANGE_IMPACT_INDEX.json](atlas/CHANGE_IMPACT_INDEX.json) | Reverse importers, callers, shared fields, Redis consumers, route clients, tests, and side effects per module/symbol/surface. |
| [ATLAS_BUILD_MANIFEST.json](atlas/ATLAS_BUILD_MANIFEST.json) | Generation commit marker with source/analyzer provenance and size/SHA-256 for every staged artifact; validate catalogs against it. |
| [MODULE_BY_MODULE_INDEX.md](atlas/MODULE_BY_MODULE_INDEX.md) | Human-readable one-row-per-module navigation table. |

Static resolution is intentionally conservative. Dynamic imports, dependency injection, Redis keys assembled from runtime data, framework callbacks, reflection, shell indirection, provider-side behavior, installed drop-ins, and cloud-side routing can escape a static graph. An unresolved edge means “inspect manually,” not “no dependency.”

## Rebuild the atlas

From the repository root:

```bash
python3 tools/build_system_reverse_engineering_atlas.py \
  --repo-root . \
  --out-dir docs/system_audit_2026_master/atlas
```

Validation:

```bash
python3 -m py_compile \
  tools/build_system_reverse_engineering_atlas.py \
  tools/tests/test_build_system_reverse_engineering_atlas.py
node --check tools/build_typescript_reverse_engineering_atlas.cjs
node tools/build_typescript_reverse_engineering_atlas.cjs --self-test --repo-root .
.venv/bin/pytest -q tools/tests/test_build_system_reverse_engineering_atlas.py
```

The generator records Git HEAD/worktree state, revalidates the tracked path list and every tracked regular-file hash/symlink/nonregular input, cross-checks TypeScript module hashes, stages all outputs, and publishes `ATLAS_BUILD_MANIFEST.json` last. Do not call a snapshot consistent unless `snapshot_consistent` and `content_inputs_unchanged` are true, start/end HEAD match, the TypeScript mismatch list is empty, and artifact hashes match the manifest.

## Change-impact workflow

For any proposed change, use this order:

1. Identify the exact symbol, field, key, route, env key, unit, or file.
2. Read its source and invariants; do not infer behavior from its name.
3. Query `CHANGE_IMPACT_INDEX.json` for direct callers/importers and shared contracts.
4. Query the Redis, config, data-field, API, and entrypoint registries for indirect consumers.
5. Recursively inspect the dependents; static results are a lower bound.
6. Check installed systemd units and drop-ins because the workstation does not exactly match versioned deployment files.
7. Check point-in-time ordering for any data/training change: `event_time`, `ingested_at`, `available_at`, `generated_at`, `feature_cutoff`, `decision_time`, and `execution_time` are distinct.
8. Check finalized-candle, dirty-sample, position-transition, risk, and exchange-mutation invariants.
9. Run focused unit/integration tests against isolated state. Do not point broad integration suites at live paper-state files or production Redis.
10. Rebuild the atlas and inspect the diff before deployment.

## Audit boundary

This audit did not enable live trading, submit/cancel/modify an order, rotate credentials, change running services, alter Redis, repair failed timers, prune replay data, run destructive retention, or execute the full integration suite against live workspace state. Those omissions are deliberate safety boundaries, not shortcuts.

## Documentation-reconciliation command ledger (2026-07-18 UTC)

This pass changed Markdown only, using `apply_patch` and confining edits to the five canonical files listed below. It did not write Python, Redis, service state or runtime artifacts. Focused pytest commands used isolated unit fixtures. The exact shell commands, in execution order (commands launched together are still listed separately), were:

<details>
<summary>Exact shell command ledger</summary>

```bash
pwd && git status --short && rg --files docs v2/docs | rg '(MASTER_SYSTEM_DOC|AI_BOT_V2_MASTER_OPERATOR_MANUAL|CURRENT_FINDINGS_AND_RISK_REGISTER|REVERSE_ENGINEERING_INDEX|V2_SYSTEM_TECHNICAL_REFERENCE)\.md$'

rg -n "paper_final_admission_contract_v3|paper_revocable_control_commit_revalidation_v1|paper_cycle_reservation|paper_precycle_current_mark_exposure_snapshot|candidate_commit_receipt|intrinsic|adaptive_gate_tuning_state|runtime_tuner_shadow|exchange_filter|CREDENTIAL_BINDING_NOT_ACCOUNT_SPECIFIC|HALTED_PERFORMANCE|G11|G12|cross_process_atomic|TOCTOU" v2/backend/app v2/backend/tests docs/MASTER_SYSTEM_DOC.md docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md

for f in docs/MASTER_SYSTEM_DOC.md docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md; do wc -l "$f"; rg -n '^#{1,4} ' "$f"; done

git diff --stat -- docs/MASTER_SYSTEM_DOC.md docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md

sed -n '1,225p' docs/MASTER_SYSTEM_DOC.md

sed -n '1,80p;375,455p;568,755p' docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md

sed -n '1,130p;181,305p;421,431p' docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md

sed -n '1,106p' docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md

sed -n '1,30p;408,480p;541,625p' v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md

wc -l v2/backend/app/services/paper_trade_management/cycle_reservation.py v2/backend/app/cli/v2_adaptive_gate_tuner.py v2/backend/app/services/adaptive_gate_tuning/runtime_tuner.py v2/backend/app/cli/v2_direct_orderbook_recorder.py v2/backend/app/cli/v2_microstructure_runtime_supervisor.py && rg -n '^def |^async def |^[A-Z][A-Z0-9_]+\s*=|schema_version|redis_key|source_key|writer|shadow|cross_process_atomic|single_active_writer|required_source_hashes' v2/backend/app/services/paper_trade_management/cycle_reservation.py v2/backend/app/cli/v2_adaptive_gate_tuner.py v2/backend/app/services/adaptive_gate_tuning/runtime_tuner.py v2/backend/app/cli/v2_direct_orderbook_recorder.py v2/backend/app/cli/v2_microstructure_runtime_supervisor.py

sed -n '1,220p;240,570p;590,960p;1040,1413p' v2/backend/app/services/paper_trade_management/cycle_reservation.py

sed -n '1,75p;184,448p;576,688p;786,1015p' v2/backend/app/cli/v2_adaptive_gate_tuner.py

sed -n '1,222p' v2/backend/app/services/adaptive_gate_tuning/runtime_tuner.py

rg -n '^def (_paper_(precycle_current_mark_exposure_snapshot|cycle_base_resource_evidence|dynamic_envelope_reservation_evidence|dynamic_envelope_reservation_evidence_rejection_reasons|cycle_reservation_contract_rejection_reasons|final_admission_point_in_time_contract|revocable_control_commit_revalidation|append_accepted_with_halted_probe_finalization|persisted_admission_projection|persisted_admission_rejection_reasons|exchange_filter_snapshot)|_adaptive_tuning_state)' v2/backend/app/cli/v2_trade_management_paper_loop.py && rg -n '^def (_refresh|.*filter|.*cache)' v2/backend/app/cli/v2_direct_orderbook_recorder.py | head -80

rg -n '_adaptive_tuning_state|adaptive_tuning.*rejection|GATE_TUNING' v2/backend/app/cli/v2_trade_management_paper_loop.py | head -100 && sed -n '24090,24380p' v2/backend/app/cli/v2_trade_management_paper_loop.py && sed -n '28060,28770p' v2/backend/app/cli/v2_trade_management_paper_loop.py

sed -n '30580,31110p' v2/backend/app/cli/v2_trade_management_paper_loop.py

sed -n '31380,31716p' v2/backend/app/cli/v2_trade_management_paper_loop.py

sed -n '31717,32120p;33770,35060p' v2/backend/app/cli/v2_trade_management_paper_loop.py

sed -n '39320,39580p' v2/backend/app/cli/v2_trade_management_paper_loop.py

sed -n '31409,31716p' v2/backend/app/cli/v2_trade_management_paper_loop.py && sed -n '31717,31910p' v2/backend/app/cli/v2_trade_management_paper_loop.py && sed -n '34620,35040p' v2/backend/app/cli/v2_trade_management_paper_loop.py

sed -n '110,380p' v2/backend/app/cli/v2_direct_orderbook_recorder.py && sed -n '1310,1455p;1580,1785p' v2/backend/app/cli/v2_direct_orderbook_recorder.py && sed -n '3460,3575p' v2/backend/app/cli/v2_trade_management_paper_loop.py

sed -n '3575,3735p' v2/backend/app/cli/v2_trade_management_paper_loop.py && sed -n '1450,1585p' v2/backend/app/cli/v2_direct_orderbook_recorder.py

rg -n '^def _paper_(revocable_control_source_materials|accepted_fill_proof_source|runtime_owner_minimal_projection|active_runtime_owner_status)|CONTINUOUS_EDGE_GUARDIAN_GATE_REDIS_KEY|PAPER_.*KEY|accepted_fills' v2/backend/app/cli/v2_trade_management_paper_loop.py | head -140 && sed -n '30020,30580p' v2/backend/app/cli/v2_trade_management_paper_loop.py && sed -n '31230,31408p' v2/backend/app/cli/v2_trade_management_paper_loop.py

sed -n '27920,28097p' v2/backend/app/cli/v2_trade_management_paper_loop.py && sed -n '4060,4170p' v2/backend/app/cli/v2_trade_management_paper_loop.py && sed -n '12000,12190p' v2/backend/app/cli/v2_trade_management_paper_loop.py

sed -n '590,835p' v2/backend/app/services/paper_trade_management/cycle_reservation.py && sed -n '835,1056p' v2/backend/app/services/paper_trade_management/cycle_reservation.py && sed -n '1081,1413p' v2/backend/app/services/paper_trade_management/cycle_reservation.py

nl -ba v2/backend/app/services/paper_trade_management/cycle_reservation.py | sed -n '825,845p' && .venv/bin/python -m py_compile v2/backend/app/services/paper_trade_management/cycle_reservation.py

.venv/bin/pytest -q v2/backend/tests/unit/services/paper_trade_management/test_cycle_reservation.py

rg -n '^def test_.*(final_admission|revocable|cycle_reservation|precycle_current_mark|exchange_filter)' v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py | tail -120

.venv/bin/pytest -q v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py -k 'final_admission or revocable or precycle_current_mark or exchange_filter'

.venv/bin/pytest -q v2/backend/tests/unit/cli/test_v2_direct_orderbook_recorder.py -k 'symbol_filter or exchange_info or provider_symbol'

.venv/bin/pytest -q v2/backend/tests/unit/cli/test_v2_adaptive_gate_tuner.py v2/backend/tests/unit/services/test_adaptive_gate_runtime_tuner.py

sed -n '1,68p' docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md && sed -n '390,452p' docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md && sed -n '693,755p' docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md && sed -n '180,305p' docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md && sed -n '1,106p' docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md

sed -n '248,296p' docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md && sed -n '127,181p' docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md && sed -n '1,30p' docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md

git diff -- docs/MASTER_SYSTEM_DOC.md docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md

git diff --check -- docs/MASTER_SYSTEM_DOC.md docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md

rg -n '^#{1,4} |paper_final_admission_contract_v3|cross_process_atomic|CREDENTIAL_BINDING_NOT_ACCOUNT_SPECIFIC|0/5|eight warnings|runtime_tuner_shadow|outcome_available_at' docs/MASTER_SYSTEM_DOC.md docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md

git diff --stat -- docs/MASTER_SYSTEM_DOC.md docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md

sed -n '195,230p' docs/MASTER_SYSTEM_DOC.md && sed -n '525,565p' v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md && sed -n '590,630p' docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md

git diff --check -- docs/MASTER_SYSTEM_DOC.md docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md && git status --short -- docs/MASTER_SYSTEM_DOC.md docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md && git diff --numstat -- docs/MASTER_SYSTEM_DOC.md docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md

rg -n "complete_pair|pairwise|correlation.*missing|missing.*correlation|same_cycle|liquidity.*missing|missing.*liquidity|microstructure.*missing|regime.*missing|DEFAULT_NEUTRAL|FAIL_CLOSED|correlation_contexts|_derive_allocator_liquidity_score|_derive_candidate_correlation_contexts" v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py | head -400

sed -n '28980,29210p' v2/backend/app/cli/v2_trade_management_paper_loop.py

sed -n '35720,35940p' v2/backend/app/cli/v2_trade_management_paper_loop.py

sed -n '37080,37480p' v2/backend/app/cli/v2_trade_management_paper_loop.py

rg -n '^def test_.*(correlation|liquidity|microstructure|regime)' v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py | tail -120

sed -n '29210,29290p' v2/backend/app/cli/v2_trade_management_paper_loop.py && sed -n '37480,37620p' v2/backend/app/cli/v2_trade_management_paper_loop.py && rg -n 'allocator_market_evidence_status|allocator_market_evidence_rejection_reasons|PAPER_ALLOCATOR_MARKET_EVIDENCE_BLOCKED' v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py

sed -n '340,375p' v2/backend/app/cli/v2_trade_management_paper_loop.py && rg -n 'CORRELATION_CANDLE_TIMEFRAME|CORRELATION_MIN_RETURN_POINTS|CORRELATION_MAX_CANDLE_AGE_SECONDS|CORRELATION_FAIL_CLOSED_EXPOSURE_PCT' v2/backend/app/cli/v2_trade_management_paper_loop.py

rg -n '^def _paper_.*adaptive.*tuning|adaptive_tuning_semantic_validation|adaptive_gate_tuning_rejection_reasons|paper_session_source|ADAPTIVE_TUNING_AUTHORITY_NOT_VALID' v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/app/cli/v2_adaptive_gate_tuner.py && rg -n 'microstructure_minimum =|FAIL_CLOSED_NO_AUTHORITATIVE_LIQUIDITY_SCORE|FAIL_CLOSED_NO_REGIME_SCORE' v2/backend/app/cli/v2_trade_management_paper_loop.py

sed -n '4160,4495p' v2/backend/app/cli/v2_trade_management_paper_loop.py && sed -n '38080,38230p' v2/backend/app/cli/v2_trade_management_paper_loop.py && sed -n '40390,40465p' v2/backend/app/cli/v2_trade_management_paper_loop.py

rg -n 'adaptive_gate_tuning_rejection_reasons|paper_session_source' v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/app/cli/v2_adaptive_gate_tuner.py && sed -n '120,150p' v2/backend/app/cli/v2_trade_management_paper_loop.py && rg -n '^def adaptive_gate_tuning_rejection_reasons|GATE_TUNING_POLICY_VALUE_FIELDS|GATE_TUNING_TTL_SECONDS' v2/backend/app/cli/v2_adaptive_gate_tuner.py

sed -n '590,900p' v2/backend/app/cli/v2_adaptive_gate_tuner.py && sed -n '4120,4170p' v2/backend/app/cli/v2_trade_management_paper_loop.py && sed -n '38690,38820p' v2/backend/app/cli/v2_trade_management_paper_loop.py

sed -n '590,760p' v2/backend/app/cli/v2_adaptive_gate_tuner.py
sed -n '760,910p' v2/backend/app/cli/v2_adaptive_gate_tuner.py
sed -n '4110,4190p' v2/backend/app/cli/v2_trade_management_paper_loop.py
sed -n '38670,38860p' v2/backend/app/cli/v2_trade_management_paper_loop.py

sed -n '4180,4495p' v2/backend/app/cli/v2_trade_management_paper_loop.py
rg -n "adaptive_tuning_semantic_validation|paper_session_source|ADAPTIVE_TUNING_AUTHORITY_NOT_VALID|source_status_policy" v2/backend/app/cli/v2_trade_management_paper_loop.py
sed -n '4560,4760p' v2/backend/app/cli/v2_trade_management_paper_loop.py
sed -n '7480,7780p' v2/backend/app/cli/v2_trade_management_paper_loop.py

sed -n '31540,32020p' v2/backend/app/cli/v2_trade_management_paper_loop.py
sed -n '33060,33170p' v2/backend/app/cli/v2_trade_management_paper_loop.py
sed -n '38220,38320p' v2/backend/app/cli/v2_trade_management_paper_loop.py
sed -n '38870,38940p' v2/backend/app/cli/v2_trade_management_paper_loop.py
sed -n '40530,40595p' v2/backend/app/cli/v2_trade_management_paper_loop.py

rg -n "under audit|open gap|semantic|adaptive tun|RE-053|allocator|0\.5|consumer" docs/MASTER_SYSTEM_DOC.md docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md

sed -n '88,126p' docs/MASTER_SYSTEM_DOC.md
sed -n '14,42p' docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md
sed -n '295,320p' docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md
sed -n '42,58p' docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md
sed -n '90,128p' v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md
sed -n '555,575p' v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md
sed -n '700,714p' v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md

rg -n "Exact command ledger|sed -n '590,900p'|Final validation|git diff --check" docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md | tail -40
sed -n '118,270p' docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md

rg -n "CORRELATION_|INCOMPLETE_REQUIRED_OPEN_PAIR_COVERAGE|FAIL_CLOSED_NO_AUTHORITATIVE_LIQUIDITY_SCORE|FAIL_CLOSED_NO_REGIME_SCORE|allocator_market_evidence|microstructure_minimum|CANONICAL_CORRELATION|canonical.*schema|canonical.*trust" v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py | tail -260
sed -n '28960,29290p' v2/backend/app/cli/v2_trade_management_paper_loop.py
sed -n '37060,37650p' v2/backend/app/cli/v2_trade_management_paper_loop.py

rg -n '^def _read_.*microstructure|schema_version.*microstructure|MICROSTRUCTURE_TRUST.*SCHEMA|microstructure_trust_reader' v2/backend/app/cli/v2_trade_management_paper_loop.py v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py | head -120
sed -n '9360,9545p' v2/backend/app/cli/v2_trade_management_paper_loop.py
sed -n '21000,21360p' v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py

sed -n '7220,7445p' v2/backend/app/cli/v2_trade_management_paper_loop.py
sed -n '36020,36245p' v2/backend/app/cli/v2_trade_management_paper_loop.py
sed -n '37740,37855p' v2/backend/app/cli/v2_trade_management_paper_loop.py

sed -n '28220,28380p' v2/backend/app/cli/v2_trade_management_paper_loop.py
sed -n '9480,9535p' v2/backend/app/cli/v2_trade_management_paper_loop.py
sed -n '28890,28945p' v2/backend/app/cli/v2_trade_management_paper_loop.py
rg -n "UNFINISHED|MISSING_CANDLE_FINALITY|FINALITY|closed_candle_flag" v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py | tail -80

rg -n '^def _closed_candle_flag_confirmed|^def _correlation_candle_point|^def _read_symbol_correlation_returns' v2/backend/app/cli/v2_trade_management_paper_loop.py
sed -n '29000,29165p' v2/backend/app/cli/v2_trade_management_paper_loop.py
sed -n '9530,9565p' v2/backend/app/cli/v2_trade_management_paper_loop.py

sed -n '245,291p' docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md
sed -n '76,95p' v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md
sed -n '94,107p' docs/MASTER_SYSTEM_DOC.md
sed -n '18,29p' docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md

rg -n "RE-040|CORRELATION_MIN|0\.65|static boundary|threshold" docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md | head -80
sed -n '200,235p' docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md

rg -n '^def test_.*adaptive.*(semantic|tuning|session|expired|receipt|producer|policy)|ADAPTIVE_TUNING_AUTHORITY_NOT_VALID|paper_adaptive_tuning_semantic_validation_v1' v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py v2/backend/tests/unit/cli/test_v2_adaptive_gate_tuner.py | tail -160
rg -n "consumer.*validation|semantic.*validation|under audit|consumer gap|six Redis|six control" docs/MASTER_SYSTEM_DOC.md docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md

rg -n "ADAPTIVE_TUNING|adaptive tuning|adaptive_tuning" docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md | head -80
rg -n "allocator_market_evidence|microstructure|correlation" docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md | head -100

sed -n '596,624p' docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md
sed -n '624,646p' docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md

git diff --check -- docs/MASTER_SYSTEM_DOC.md docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md
git diff --stat -- docs/MASTER_SYSTEM_DOC.md docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md
rg -n "consumer.*under audit|consumer gap at this cut|complete consumer validation.*still|incomplete deployed proof|six Redis|six control" docs/MASTER_SYSTEM_DOC.md docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md

sed -n '28990,29170p' v2/backend/app/cli/v2_trade_management_paper_loop.py
rg -n "missing.*finality|finality.*missing|closed.*fallback|UNFINISHED_CANDLE|MISSING_EXPLICIT" v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py | tail -100

sed -n '35990,36255p' v2/backend/app/cli/v2_trade_management_paper_loop.py
sed -n '36255,36330p' v2/backend/app/cli/v2_trade_management_paper_loop.py
sed -n '29200,29295p' v2/backend/app/cli/v2_trade_management_paper_loop.py

sed -n '18,28p' docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md
sed -n '604,632p' docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md
sed -n '98,116p' docs/MASTER_SYSTEM_DOC.md
sed -n '202,214p' docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md
sed -n '278,286p' docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md
sed -n '80,94p' v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md
```

</details>

Modified files for this documentation task:

- `docs/MASTER_SYSTEM_DOC.md`
- `docs/system_audit_2026_master/AI_BOT_V2_MASTER_OPERATOR_MANUAL.md`
- `docs/system_audit_2026_master/CURRENT_FINDINGS_AND_RISK_REGISTER.md`
- `docs/system_audit_2026_master/REVERSE_ENGINEERING_INDEX.md`
- `v2/docs/V2_SYSTEM_TECHNICAL_REFERENCE.md`
