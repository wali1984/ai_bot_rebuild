# Authenticated Local Research Inference Checkpoint

- Checkpoint UTC: `2026-07-23T10:37:12Z`
- Branch: `codex/strategy-receipt-promotion-20260723`
- Parent checkpoint commit: `790ce5ae96`
- Implementation commit: `2bf9d3b5c57a97cc28f99ceec712e522cbb4dafa`
- Implementation pushed: yes; local and origin were `0/0` ahead/behind immediately after push.
- Runtime scope: authenticated, quarantined local trainer-candidate inference only.
- Prediction, serving, PAPER, risk, allocator, margin, live exchange, and order authority granted: `0`.
- Services, Redis, publishers, and exchange connections changed: `0`.

## Evidence counts

| Evidence | Count/result |
|---|---:|
| Production modules changed/added | 2 |
| Test modules changed/added | 2 |
| Focused tests passed | 11/11 |
| Production modules byte-compiled | 2/2 |
| Test modules byte-compiled | 1/1 new test module |
| Files checked by Ruff | 4 |
| Ruff findings | 0 |
| `git diff --check` findings | 0 |
| Raw receipt public fields checked | 56 |
| Handle public fields sealed/checked | 32/32 |
| Explicit false authority fields | 13/13 |
| Runtime clocks evaluated | 7 |
| PIT ordering edges enforced | 6 |
| Exact checkpoint-load postconditions | 23/23 |
| Current-release/source digests reverified | 2 at open and again per inference |
| Independent focused-review files/callables | 4 / 15 |
| HTTP routes/endpoints inspected | 0 |
| UI screenshots captured | 0 |
| Frontend/iOS builds | 0; not part of this backend component family |
| Services started/stopped/restarted | 0 |
| Redis keys read/written | 0 / 0 |
| Remaining defects in this committed seam | 0 known |

## What the boundary now proves

The new public factory opens one exact local-research checkpoint only after:

1. exact config and five-way HMAC-role separation validation;
2. singleton checkpoint-ID selection from the local-research lineage;
3. existing local candidate-manifest HMAC verification;
4. exact clean Git release and complete optimizer source-closure matching;
5. exact-ID/private-copy checkpoint loading; and
6. 23 load, evidence, causal-lineage, fingerprint, ABI, and eval-state
   postconditions.

The returned handle seals all 32 public fields plus the process-local model
owner. It freshly validates each immutable profiled record and its transform,
capture set, payload stores, and two provenance-ledger entries. It constructs
the real masked tensor with `35/446` available features (`7.847533632286996%`),
not the false `100%` coverage produced by a bare vector.

The output is raw logits only. Calibrated confidence and profitability remain
`null`; all 13 consumer, trainer, prediction, serving, PAPER, live, exchange,
deployment, order, execution, and runtime-wiring authorities remain literal
`false`.

## PIT and replay ordering

The runtime enforces:

`candidate_manifest_observation_time < checkpoint_generated_at < feature_cutoff <= record_generated_at <= source_decision_time <= inference_started_at <= hypothesis_generated_at`

`hypothesis_generated_at` is stamped only after successful model execution and
output validation. A separate pre-forward clock rejects future-dated inputs,
so a slow inference cannot make a future record admissible.

Source-decision monotonicity is process-wide across handles for the exact
`(checkpoint_id, candidate_contract_sha256, symbol, timeframe)` key. Reopening
the same candidate cannot replay the same or an older record during the process
lifetime. No durable or cross-process replay claim is made at this boundary.

## Defects fixed in this family

1. There was no public API jointly authenticating the local candidate,
   verifying the current release/source closure, exact-loading its checkpoint,
   and exposing authority-free inference.
2. Initial receipt hashing passed tuples to a strict-JSON hasher. Tuple fields
   are now converted to JSON lists identically for construction, validation,
   and payload emission.
3. The initial generation timestamp was captured before model execution. It is
   now captured after successful output validation while retaining a separate
   future-input preflight clock.
4. The initial handle seal omitted checkpoint time and most provenance and
   authority fields. It now binds all 32 public fields.
5. `consumer_eligible` and `trainer_admission_authorized` were absent from the
   handle. Both are explicit and false.
6. Release/source verification could become stale after handle open. Both
   digests are recomputed before every inference.
7. Per-handle monotonic state allowed replay after reopening. The guard is now
   shared for the exact candidate/pair during process lifetime.
8. Malformed model outputs, manager construction failures, and malformed load
   results could leak raw exceptions. The public boundaries now return stable,
   payload-free inference errors.

The model's checkpoint loader and torch forward path already enforce eval mode
and `no_grad`; no duplicate or strategy/model behavior change was made.

## Focused regressions passed

1. exact candidate open and all 13 false-authority handle fields;
2. complete handle-seal tamper rejection;
3. manager-initialization error wrapping;
4. negative exact-load postcondition rejection;
5. fresh immutable-record revalidation with true `35/446` coverage;
6. post-forward hypothesis timestamp and strict JSON receipt seal;
7. same-handle replay rejection;
8. reopened-handle replay rejection;
9. per-inference release/source-closure drift rejection;
10. malformed model-output stable rejection;
11. immutable-record tamper and pre-checkpoint PIT rejection; and
12. release SHA, source-closure SHA, and malformed expectation checks (within
    the single focused verifier test).

The pytest count is 11 because several related assertions are grouped in the
same focused test.

## Files in implementation commit

1. `v2/backend/app/services/native_trainer/authenticated_profiled_supervised_optimizer_execution_v1.py`
2. `v2/backend/app/services/native_trainer/locally_authenticated_profiled_research_inference_v1.py`
3. `v2/backend/tests/unit/services/native_trainer/test_authenticated_profiled_supervised_optimizer_execution_v1.py`
4. `v2/backend/tests/unit/services/native_trainer/test_locally_authenticated_profiled_research_inference_v1.py`

## Verification commands

```bash
PYTHONPATH="$(pwd)" '/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python' -m pytest -q v2/backend/tests/unit/services/native_trainer/test_locally_authenticated_profiled_research_inference_v1.py v2/backend/tests/unit/services/native_trainer/test_authenticated_profiled_supervised_optimizer_execution_v1.py::test_inference_release_source_closure_requires_exact_clean_match

'/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python' -m ruff format v2/backend/app/services/native_trainer/locally_authenticated_profiled_research_inference_v1.py v2/backend/tests/unit/services/native_trainer/test_locally_authenticated_profiled_research_inference_v1.py

'/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python' -m ruff check v2/backend/app/services/native_trainer/locally_authenticated_profiled_research_inference_v1.py v2/backend/tests/unit/services/native_trainer/test_locally_authenticated_profiled_research_inference_v1.py

'/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python' -m ruff check v2/backend/app/services/native_trainer/authenticated_profiled_supervised_optimizer_execution_v1.py v2/backend/tests/unit/services/native_trainer/test_authenticated_profiled_supervised_optimizer_execution_v1.py

'/home/wali/Desktop/AI BOT REBUILD/.venv/bin/python' -m py_compile v2/backend/app/services/native_trainer/locally_authenticated_profiled_research_inference_v1.py v2/backend/app/services/native_trainer/authenticated_profiled_supervised_optimizer_execution_v1.py v2/backend/tests/unit/services/native_trainer/test_locally_authenticated_profiled_research_inference_v1.py

git diff --check
git commit -m "feat(trainer): authenticate quarantined candidate inference"
git push origin codex/strategy-receipt-promotion-20260723
git rev-list --left-right --count HEAD...origin/codex/strategy-receipt-promotion-20260723
```

Additional bounded read-only commands were `git status`, `git log`, `git diff`,
`git check-ignore`, `rg`, `sed`, `wc`, `sha256sum`, and the current-goal/agent
status checks. No system-wide atlas, service audit, Redis scan, or already
proven end-to-end audit was rerun.

## Deployment truth and next bounded family

This commit intentionally does **not** make the trainer publisher live. The
previous local candidate was produced by an older release/source closure and
must fail this new current-release gate. The trainer must produce a new
immutable candidate from the clean branch HEAD after this checkpoint commit
(which contains implementation commit `2bf9d3b5c5`) before this seam can open
it.

Next: materialize bounded, PIT-safe shadow hypotheses into explicit-cost
matured outcomes and calibration evidence while keeping every downstream
authority false. Commit/push that component family and its checkpoint before
any prediction-serving or PAPER publisher activation.
