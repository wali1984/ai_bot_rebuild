# GOAL — Bring Paper Trading Back Online (Trainer Data Supply → Routable Predictions → Paper Closes)

- **Goal ID:** `V2_BRING_PAPER_TRADING_ONLINE`
- **Owner lane:** Codex (trainer + data-supply). Web/iOS/product are DONE — out of scope.
- **Authored:** 2026-07-23, from live runtime evidence + Codex's M1/M2 report.
- **Prime directive:** Restore the end-to-end paper pipeline so the paper loop produces trades again, as fast as possible, without loosening a single safety gate and without circling on off-critical-path work.

---

## 1. One-sentence objective

Make the commissioned trainer produce a real evaluated challenger from **point-in-time-reconstructed historical training data**, so it publishes routable predictions, so the orchestrator fills `v2:signals:paper`, so the paper loop opens and closes paper trades again — ending the ~6-day drought (no close since 2026-07-17T22:48Z).

## 2. Confirmed starting state (do NOT re-derive or re-audit)

- **Milestone 1 = TRUE.** Deployed trainer runs release `974caa6c26`. Mark-price seeder reconciled and pushed (`6801f44eb6`); seeder tests + lint pass. The 24,959-line paper-loop divergence was correctly NOT merged — leave it.
- **Milestone 2 = FALSE — this is the entire remaining blocker.** `v2:trainer:champion_challenger_status.backtests_processed.train_rows = 0`, `untouched_holdout_rows = 0`. Blocker taxonomy (all seven must clear):
  `ACTION_SPECIFIC_COST_COVERAGE_INCOMPLETE`, `HOLDOUT_ROWS_MISSING`, `INSUFFICIENT_DISTINCT_DECISION_TIME_GROUPS`, `INSUFFICIENT_TRAIN_ROWS`, `TRAINING_ROWS_MISSING_AFTER_4H_PURGE`, `VALIDATION_ROWS_MISSING`, `VALIDATION_ROWS_MISSING_AFTER_4H_PURGE`.
- **Root cause (Codex-confirmed):** the challenger reads only the legacy durable snapshot archive; there is **no PIT-safe historical-candle → feature/cost/MTF-record importer** feeding it. `profiled_training_ledger_loader_v1` and the canonical 5m labels exist but are **separate, unwired sources**. Naive candle-only backfill is forbidden — it would violate the provenance/cost contracts the causal refactor requires.
- **Downstream is healthy and honestly empty**, waiting on the trainer: `0/400` predictions route; `v2:signals:paper` empty; paper loop `intents_built` idle; performance circuit breaker halted on the stale 91-trade cohort (PF 0.658).
- **Safety confirmed:** `live_gate=blocked_human_only`, `account_mode=paper_shadow_only`, no orders / no leverage / no margin mutation. This goal MUST preserve all of that.

## 3. Definition of DONE (the whole goal — all must be TRUE, each proven by the named runtime signal)

1. `v2:trainer:champion_challenger_status.backtests_processed.train_rows > 0` **and** `untouched_holdout_rows > 0` **and** `validation_rows > 0`, with **all seven** blocker reasons above cleared.
2. `best_challenger_id != null` and `holdout_improvement` populated (a challenger was actually evaluated on untouched holdout).
3. ≥1 fresh `v2:prediction:*` key with `routes_to_orchestrator = true`, age < 10 min.
4. `v2:signals:paper` length > 0 **and** paper `trade_management` status shows `intents_built > 0`.
5. ≥1 paper close with `exit_price_utc` later than the moment the chain came online (drought broken).
6. ≥10 fresh paper closes including ≥1 multi-fill → clears `WQ-R34` / CG-F049 / CG-F050 and lets guardian G13/G14 recompute on **real** data (pass/fail then reflects the model, not a frozen cohort).

When all six hold, the system is back online in paper and this goal is complete.

## 4. The core deliverable — ONE PIT feature-reconstruction importer

This is the only new component to build. Build it once, correctly, inside the commissioned trainer's existing data-loading seam (reuse `profiled_training_ledger_loader_v1`; do not spawn a parallel ad-hoc path).

**What it does:** for each historical decision timestamp `t` across a chosen backfill window, reconstruct the training row exactly as it would have existed at `t`, with no look-ahead, and write it into the store the challenger's train/holdout/validation reader consumes.

**Per-row contract (every row MUST carry, or the row is rejected — this is how the seven blockers clear):**
- **Point-in-time feature vector** built only from data with `available_at <= t` (satisfies causal boundary; no future leakage).
- **Action-specific cost evidence** for each admissible action (long/short) at `t` — spread/fee/slippage as-of `t` (clears `ACTION_SPECIFIC_COST_COVERAGE_INCOMPLETE`).
- **Multi-timeframe (MTF) record** consistent with the canonical closed-candle finality rules.
- **Label** joined from the **canonical 5m labels** source (not recomputed ad hoc).
- **Provenance / source lineage** stamped per field (satisfies the provider/causal contracts; no unauthenticated or unbounded source).
- **Decision-time group key** so rows aggregate into distinct temporal groups.

**Window / volume sizing rule (prevents "rows exist but purge/splits empty them"):** read the challenger's own configured minimums for train / validation / holdout and the 4h embargo purge, then size the backfill window and decision-time cadence so that **after** the 4h purge **and** the train/val/holdout split, every bucket exceeds its minimum with margin, and distinct-decision-time-groups exceeds its threshold. Log target-vs-achieved counts for each bucket.

**Non-negotiable importer properties:** deterministic and idempotent (re-runnable without dupes); reuses existing loaders (`profiled_training_ledger_loader_v1` + canonical 5m labels + the durable snapshot archive schema) rather than duplicating them; writes into the exact store/schema the challenger already reads (or repoints the reader — whichever is smaller and cleaner); zero look-ahead by construction; covered by a focused unit/integration test proving PIT-correctness and provenance/cost completeness on a small fixture before any full backfill run.

## 4a. CAS integrity ruling — resolving `PROFILED_TRAINING_COST_CAS_INVENTORY_NOT_EXACT` (loader:1352) WITHOUT violating provenance

This check fails when the objects physically present in the cost content-addressed store do **not** exactly equal the CAS addresses the cost artifact declares (byte-counts included). The store is immutable and hash-addressed. **Do NOT "repair" it by adding, deleting, or rewriting stored objects to force equality — that fabricates/mutates authenticated cost evidence and is forbidden.** Resolve by diagnosis, in this order:

1. **Diagnose the mismatch direction first (read-only, no mutation).** Emit the symmetric difference between `expected_inventory` and `inventory`: which digests are *declared but physically absent* (under-supply), which are *present but undeclared* (over-supply), and any byte-count deltas. One bounded diagnostic. Report the counts before doing anything else.
2. **If the physical objects exist but the reader mis-enumerates them** (wrong `sha256/xx/…` shard walk, dedup, path-prefix, or ordering bug) → this is a **code fix in the enumeration/reader logic**. Legitimate. Fix the reader so `inventory` reflects true physical contents; do not touch the stored objects.
3. **If the CAS is genuinely missing declared cost objects** (the artifact over-declares receipts that were never captured for that period) → the artifact is **cost-incomplete**. Do NOT fabricate the missing evidence. **Exclude those decision times from the import** (they cannot satisfy action-specific cost coverage) and, per the Section 4 window-sizing rule, **widen the backfill window to periods where fully-authenticated cost bundles exist** so the surviving contract-valid rows still exceed the post-purge train/val/holdout minimums. Fewer rows that are all contract-valid beats more rows that break provenance.
4. **Never** make the store contents match the manifest. Only the enumeration code or the row-inclusion set may change. If neither (2) nor (3) resolves it, STOP and report the exact symmetric-difference evidence as a new distinct blocker.

## 4b. Runtime-bound ruling — importer exceeds the bounded run (exit 124 at 900s, no counters)

The enumeration fix is correct (CAS diff was 5 extra / 0 absent / 0 byte-deltas → pure over-inclusion, resolved in reader code, no store mutation). The remaining D2 blocker is that a single full-observation scan does not fit the 900s bound. Do NOT just raise the timeout and hope — restructure so the importer makes visible, monotonic, resumable progress:

1. **Incremental + checkpointed + idempotent.** Partition the fixed-observation set into bounded shards (by decision-time window or fixed batch count) sized to complete well within the runtime bound. Each shard writes its reader rows **durably and atomically** (a mid-shard kill must never leave half-written/corrupt reader state) and records a checkpoint of the last completed shard, so the next bounded run **resumes** and never re-does completed shards.
2. **Emit progress every shard** — rows imported, rows excluded (with reason), shards done / remaining, elapsed. No more opaque 900s black box; a bounded run must show counters advancing.
3. **Target the minimum, not the maximum — this is the fast path online.** The D2/D3 exit criteria are `train_rows>0` and post-purge train/val/holdout ≥ their configured minimums — NOT "import all history." Order shards so fully-authenticated, purge-eligible windows import first, and **STOP the backfill as soon as the challenger's post-purge minimums are provably exceeded.** Getting online early beats exhaustive coverage; the rest can backfill later.
4. **Optimize only if a single shard still won't fit** (not speculatively): memoize CAS-object verification so an authenticated cost object shared across rows is read/hashed once, not per-row.
5. Provenance/safety unchanged: no CAS mutation, no fabricated rows, exclude-don't-invent still applies per Section 4a.

## 4c. AUTHORIZED — trainer compute & instant-shard spec governs D2/D3 throughput

The operator has authored and **authorized implementation** of [`Codex-redefined-goal.md`](./Codex-redefined-goal.md) (CUDA-only training + instant-shard requirements). That spec is the **authoritative, binding requirement for the trainer-compute and shard-throughput dimension** and is the detailed resolution to the §4b / D2 runtime-bound blocker. It supersedes §4b where more specific. Read it in full; the load-bearing parts for getting online now:

- **Remove the per-shard full historical scan (the "~60,000-snapshot freeze").** Current trainer runs `v2_native_cuda_trainer_persistent_loop.py` with `--scan-limit 250000` — the likely freeze source. Replace with the incremental design: build/validate the frozen snapshot set once; persist immutable manifest (version, row count, checksum, max-seq, cutoff); per shard process only the delta since the last committed head; reuse the unchanged historical set. Complexity ∝ new rows, not total rows. Targets: 1-row shard prep < 10s, small shard < 30s, first CUDA update after an authenticated shard < 60s.
- **Separate the online CUDA trainer from the evidence-maintenance worker.** Large historical scans / manifest reconstruction / receipt verification run OFF the online training critical path and must not hold the trainer lock or block a valid new shard.
- **Current state grounding (verified):** GPU RTX 5080 healthy, CUDA available, util ~14% (idle) — so CUDA-availability/fail-closed items are already satisfied; classify the trainer as `CUDA_TRAINING_WAITING_FOR_DATA` / `BLOCKED_NO_AUTHENTICATED_ROWS`, not a CUDA fault. The binding work is the incremental-shard redesign + the data supply (§4/§4a/§4b), not CUDA recovery.
- **One authoritative CUDA trainer + fresh telemetry + acceptance proof.** Enforce single canonical trainer writer (stop duplicate/observer writers); publish the telemetry fields the spec lists; before reporting the trainer restored, prove **two consecutive CUDA optimizer steps** on authenticated shards with no CPU fallback and no per-shard full scan.
- **Boundaries unchanged:** performance changes must not weaken point-in-time / finality / receipt / model-identity validation (ties to §4a — no fabrication, no CAS mutation). Live stays blocked; paper-shadow only.

This D2/D3 throughput fix and the CUDA acceptance grade in `Codex-redefined-goal.md` are the gate to `train_rows>0` → challenger → routable predictions → paper trades. Implement under the same fix-and-continue autonomy (§6).

## 5. Ordered execution (each step gated on the prior step's runtime proof)

- **D1 — Build + unit-prove the importer** (Section 4). Proof: focused test passes showing a reconstructed row with full PIT features + action-specific cost + MTF + provenance + label on a fixture; no look-ahead.
- **D2 — Run the bounded backfill** and wire it to the challenger reader. Proof: challenger's train/holdout/validation readers return the imported rows; logged achieved counts exceed minimums post-purge.
- **D3 — Rerun the challenger proof.** Proof: Definition-of-Done items 1 & 2 TRUE.
- **D4 — Confirm routable predictions.** Proof: DoD item 3 TRUE. (If predictions still don't route with a valid challenger, that is a new distinct blocker — STOP and report it with the exact gate/field.)
- **D5 — Confirm chain to paper.** Proof: DoD item 4 TRUE.
- **D6 — Clear the stale circuit breaker via the DESIGNED lever only.** Once D4 is TRUE, use the existing **paper session-reset endpoint (CG-F042)** — bounded and logged — to drop the frozen 91-trade negative cohort so bootstrap/exploration entries admit. Do NOT disable the breaker, widen gates, or hardcode thresholds. Proof: DoD item 5 TRUE (a new close after reset time).
- **D7 — Accumulate ≥10 fresh closes incl. ≥1 multi-fill.** Proof: DoD item 6 TRUE.

## 6. Execution mode — FIX AND CONTINUE autonomously (do not stop-and-wait on ordinary blockers)

**Default: when a step's proof is not TRUE, fix the cause and continue — do NOT stop and hand back.** Keep driving the ladder (D1→D7) through every ordinary/mechanical blocker until a Section 3 signal turns TRUE or you hit a STOP-class item below. Fix, commit (exact paths), rerun the proof, advance. No pausing for approval on routine fixes.

**Ordinary blockers you MUST just fix and continue (non-exhaustive):** wrong/symlinked paths (use canonical `/home/wali/ai_bot_local_data/...`), timeouts (shard + checkpoint per §4b), enumeration/reader bugs (§4a case 2), config/env/credential wiring, missing directories, retryable I/O, schema field mapping, test failures in your own new code. These do not warrant a halt.

**STOP-class — the ONLY reasons to halt and ask the operator (these are genuinely unsafe or ambiguous):**
1. A fix would require **mutating an immutable/protected store or fabricating data** (CAS contents, authenticated cost/provenance evidence) — see §4a. Exclude-don't-invent instead; only escalate if that can't meet minimums.
2. A fix would require **loosening/bypassing/hardcoding a safety, risk, edge, or circuit-breaker gate**, enabling live, or any exchange/leverage/margin mutation.
3. A fix would require **editing a forbidden file** (§7: paper loop, `v2/frontend/**`, `v2/mobile/**`) or the protected trainer venv beyond the deployed release.
4. A **genuine architectural fork with no safe default** (two plausible designs with materially different risk).
5. **True circling:** the *same* blocker recurs a 3rd time despite two distinct fix attempts — stop and report it rather than loop.

Everything outside that list: fix it and keep going.

**Still forbidden while continuing:** only Section 3's six runtime signals count as progress (not summaries/plans/coverage docs); do not write new planning/evidence artifacts instead of moving a proof to TRUE; build the importer once (no parallel importers or temporary candle-only shims — the provenance/cost contract is the point).

## 7. Forbidden actions (hard stops)

- Do NOT merge the commission branch's paper-loop copy (24,959-line divergence) or edit `v2/backend/app/cli/v2_trade_management_paper_loop.py` — keep local.
- Do NOT touch `v2/frontend/**` or `v2/mobile/**` (web + iOS are audited, deployed, done).
- Do NOT regenerate the system atlas; do NOT re-run visual/product/route audits; do NOT produce any new `FINAL_PRODUCT_AUDIT_*`, coverage-matrix, or completion-evidence document.
- Do NOT loosen, bypass, or hardcode any admission/edge/risk/circuit-breaker gate to force trades. The model must earn admission on reconstructed data.
- Do NOT `git add -A`; stage only the exact paths of the slice you are committing.

## 8. Safety invariants (non-negotiable, unchanged)

`live_gate` stays `blocked_human_only`; `account_mode=paper_shadow_only`; no exchange orders, no leverage change, no margin-mode change; do not mutate the protected trainer venv beyond the already-deployed `974caa6c26`; Redis inspection is exact-key or bounded `SCAN MATCH … COUNT` only — no `KEYS`, no unbounded scan.

## 9. Reporting cadence (report on progress, not on every blocker)

Do NOT report-and-wait after each blocker. Report only when: (a) a Section 3 signal turns TRUE (milestone reached), or (b) you hit a STOP-class item (§6) and must halt, or (c) a periodic heartbeat while a long fix/backfill runs. Keep it ≤10 lines: `current D-step · the proof field and its actual value · what you just fixed and committed · next concrete action.` No prose essays, no re-statement of this goal. Between reports, keep fixing and advancing.

## 10. Acceptance

Goal is accepted when Section 3 items 1–6 are all TRUE from live Redis, with the importer committed (exact paths, focused test green), all safety invariants intact, and the first ≥10 fresh paper closes recorded. At that point paper trading is back online and WQ-R34 / CG-F049 / CG-F050 can be independently revalidated.
