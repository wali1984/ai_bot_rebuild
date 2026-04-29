# Phase 1 Plan Review

## 1. Verdict
PASS_WITH_REQUIRED_CHANGES

The plan is directionally strong and safety-oriented, but not implementation-ready yet. Several controls required by your corrected failure model are missing or only implicit.

## 2. Corrected Failure Model Check
Assessment: PARTIAL PASS

What is covered:
- External/manual inventory can mask system performance and must be treated differently.
- Adoption path and downstream bot management risk are acknowledged.
- Quarantine intent is explicitly defined.

What is missing/weak:
- Not explicit enough that **RAVE exposure was manual-origin in retained window** and bot was only downstream manager.
- Needs a required provenance-evidence chain for “origin not bot-generated in window” (proposal/event/exec lineage), not just `origin_kind` labels.
- Needs explicit policy distinction between `EXTERNAL_MANUAL` and `UNKNOWN_EXTERNAL` at enforcement level.

## 3. Patch Order Review
Assessment: NEEDS CHANGE

Current order is mostly sensible, but unsafe between patches versus required order.

Required safer order should be:
1. Provenance schema + immutable first-seen evidence
2. External/manual quarantine enforcement
3. Disable/gate manual hedge override
4. Risk assertion integration
5. Execution feedback attribution hardening
6. Duplicate accounting dedupe unification
7. Degraded-state fail-closed gates (`DQ` degraded, `ORCH_STALLED`)
8. Margin/leverage live blocks

Gaps in current order:
- `Risk assertion integration` appears before `manual hedge override hardening`; this can leave a temporary risk-add bypass.
- No explicit step for degraded-state fail-closed gating.
- No explicit final step for live margin/leverage hard blocks.

## 4. File/Function Coverage Review
Assessment: PARTIAL

Covered in plan:
- `trading/trader.py`
- `risk/assertions.py`
- `rl/orchestrator_worker.py`
- `rl/hedge_manager_v3.py`
- `rl/trade_feedback.py`
- `rl/profit_bank.py`
- `config.py`
- `trading/signal_router.py`

Missing (required by your checklist):
- `trading/base_executor.py`
- `trading/stealth_stops.py`
- `risk/halt_manager.py`
- `rl/hybrid_trainer.py`
- Audit/reporting readers of `executed_signals` (PnL/audit scripts)

## 5. Safety Gate Coverage Review
Assessment: PARTIAL

Present:
- Immutable provenance intent
- Quarantine with reduce-only default
- Manual hedge override gating
- Attribution + dedupe intent

Missing explicit hard bans for quarantined external/unknown inventory:
- No DCA (`ADD_*`, `INCREASE_*`, scale-ins)
- No hedge expansion
- No `ADJUST_LEVERAGE`
- No `FLIP`
- No cross-margin rescue logic

Also missing:
- Explicit fail-closed behavior under degraded telemetry (`dq_source_ok=false`/stale) and `ORCH_STALLED`.

## 6. Test Coverage Review
Assessment: PARTIAL

Covered:
- RAVE regression concept
- Risk-add blocked on quarantined legs
- Reduce-only allowed by policy
- Dedupe checks
- Feedback provenance checks (partial)

Missing required tests:
- Classification proof: leg becomes `EXTERNAL_MANUAL` or `UNKNOWN_EXTERNAL`
- No hedge cap override applied to external/unknown
- No `ADJUST_LEVERAGE` for manual/unknown
- No duplicate `executed_signals` rows keyed by same `exchange_order_id`
- Feedback includes provenance + **parent decision ID** deterministically
- PnL audit split: manual-origin exposure vs bot-management outcome

## 7. Paper-Mode Acceptance Review
Assessment: PARTIAL

Existing acceptance criteria are good but incomplete.

Missing required criteria:
- 100% attribution coverage target on execution events
- No risk-add during DQ degraded state
- No risk-add while `ORCH_STALLED`
- No cross-margin/high-leverage live behavior for external/unknown paths
- Explicit “RAVE regression pass” as gating criterion

## 8. Blocking Gaps
1. Missing explicit hard-ban matrix for quarantined inventory (`no DCA`, `no hedge expansion`, `no FLIP`, `no ADJUST_LEVERAGE`, `no cross-margin rescue`) — **blocking before implementation**.
2. Patch order unsafe (manual hedge override gating must precede risk assertion rollout) — **blocking before implementation**.
3. Missing degraded-state fail-closed stage (`DQ` degraded, `ORCH_STALLED`) — **blocking before implementation**.
4. Missing mandatory file coverage for `trading/base_executor.py`, `trading/stealth_stops.py`, `risk/halt_manager.py`, `rl/hybrid_trainer.py`, audit readers — **blocking before implementation**.
5. Missing attribution requirement for parent decision lineage ID in feedback — **blocking before implementation**.

## 9. Non-Blocking Gaps
- Add explicit retained-window provenance proof language (manual-origin determination method) — **can be fixed during patch**.
- Tighten terminology split (`EXTERNAL_MANUAL` vs `UNKNOWN_EXTERNAL`) in acceptance tests — **can be fixed during patch**.
- Expand validation grep matrix for audit split outputs — **documentation-only**.
- Add optional stress/replay scenarios for delayed feedback streams — **optional later**.

## 10. Recommended Patch 1 Scope
Patch 1 should be **provenance + quarantine hard-stop only** (no strategy behavior changes):
- Immutable provenance schema and first-seen evidence fields.
- External/manual/unknown classification write path.
- Quarantine enforcement that permits only reduce-only protective actions.
- Immediate hard bans: no DCA, no hedge expansion, no FLIP, no ADJUST_LEVERAGE, no cross-margin rescue.
- Minimal telemetry: provenance + parent decision ID on skip/exec payloads.
- Kill switches fail-safe by default.

## 11. Final Implementation Readiness
NOT READY

Readiness can move to READY only after:
- Blocking gaps are resolved in plan text,
- patch order is corrected to safe sequencing,
- file/function coverage includes all required modules,
- paper-mode acceptance criteria includes degraded-state and ORCH-stall fail-closed gates.
