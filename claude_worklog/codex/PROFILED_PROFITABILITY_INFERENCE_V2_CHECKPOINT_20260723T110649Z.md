# Profiled Profitability Inference V2 Checkpoint

Timestamp: `2026-07-23T11:06:49Z`  
Branch: `codex/strategy-receipt-promotion-20260723`  
Implementation commit: `70e5cf3b21a7e0ba0272e57db5dced8e43c1d094`  
Family status: implementation complete, committed, and pushed

## Outcome

The authenticated local research inference boundary now has a separate V2
receipt that preserves the model outputs needed for future selected-action
profitability calibration without granting prediction, serving, PAPER, live,
deployment, execution, exchange, or order authority.

The frozen V1 contract remains a distinct sibling type with the same 56 public
fields, schema, classification, payload surface, raw-logit selection check, and
authority posture. V2 has 64 public fields and adds:

1. confidence-head schema version;
2. profitability label semantics;
3. ordered `("long", "short")` head labels;
4. ordered uncalibrated directional raw probabilities;
5. selected-action directional flag;
6. selected directional raw profitability value or `None`;
7. all seven model-adjusted action probabilities; and
8. the model expected-move output in basis points.

Every added field participates in `hypothesis_binding_sha256`. V2 accepts only
native finite floats, exact tuple containers, probabilities in `[0, 1]`, and a
normalized seven-action distribution. The selected action is restricted to the
model's opening trio (`hold`, `long`, `short`) and is rederived as the argmax of
the adjusted opening probabilities. Non-directional selection carries no fake
profitability value. `confidence_calibrated` and `profitability_probability`
remain `None`.

## Evidence counts

- Production files changed: 1
- Test files changed: 1
- Routes inspected/changed: 0 / 0
- API endpoints compared/changed: 0 / 0
- Screenshots captured: 0
- Services restarted or activated: 0
- Redis reads/writes: 0 / 0
- Exchange/PAPER/live/order paths changed: 0
- V1 public fields checked: 56 / 56
- V2 public fields checked: 64 / 64
- V2-added fields hash-bound: 8 / 8
- Adjusted action probabilities bound: 7 / 7
- Permitted selected opening indices: 3 / 3
- False downstream-authority fields checked: 13 / 13
- Focused tests passed: 13 / 13
- Python byte-compile checks passed: 2 / 2 files
- Ruff checks passed: 2 / 2 files
- Commit whitespace checks passed: 1 / 1 commit
- Reviewer findings resolved: 5 / 5
- Defects remaining in this bounded family: 0
- Implementation diff: 547 insertions, 13 deletions

## Point-in-time and authority invariants retained

- Candidate manifest authentication and exact checkpoint loading are unchanged.
- Current clean release and source closure are revalidated before each forward.
- Immutable record/evidence is freshly revalidated before tensor construction.
- The existing checkpoint, feature cutoff, record generation, source decision,
  inference start, and hypothesis generation clock ordering remains enforced.
- Real data coverage remains `35 / 446` (`7.847533632286996%`), never 100%.
- The profiled record remains explicitly unready for normal trainer admission.
- All 13 downstream authority flags remain false.
- Process-local monotonic source ordering remains enforced across reopened
  handles; durable cross-process ordering is still a later boundary.

## Validation commands

```text
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_locally_authenticated_profiled_research_inference_v1.py
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/ruff check v2/backend/app/services/native_trainer/locally_authenticated_profiled_research_inference_v1.py v2/backend/tests/unit/services/native_trainer/test_locally_authenticated_profiled_research_inference_v1.py
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m py_compile v2/backend/app/services/native_trainer/locally_authenticated_profiled_research_inference_v1.py v2/backend/tests/unit/services/native_trainer/test_locally_authenticated_profiled_research_inference_v1.py
git show --check --oneline HEAD
```

Focused result: `13 passed in 87.88s`.

An additional optimizer-suite probe produced 18 passing tests and 14 setup
errors because the isolated worktree intentionally does not match the deployed
TA-Lib interpreter-path identity. The repeated setup reason was
`AUTHENTICATED_OHLCV_TRANSFORM_V1_TALIB_ENVIRONMENT_MISMATCH`; it was not a
failure in this two-file family and was not rerun.

## Honest downstream state

This commit does not activate a publisher or make a signal tradable. The next
family must bind the exact V2 receipt to the authenticated causal-cost artifact,
use the decision-time order-book mid as entry reference, and mature only against
finalized canonical 5-minute labels committed before observation. Existing
candidates were produced by an older source closure and must fail the new
current-release gate; a fresh candidate is required after the final clean code
release is established.

The existing 900-second counterfactual horizon is a pinned model-label ABI, not
a market-admission threshold. It is preserved here rather than silently changed.
No immutable shadow outcome artifact or restart-persistent maturity index exists
yet.

## Files in the implementation commit

- `v2/backend/app/services/native_trainer/locally_authenticated_profiled_research_inference_v1.py`
- `v2/backend/tests/unit/services/native_trainer/test_locally_authenticated_profiled_research_inference_v1.py`

