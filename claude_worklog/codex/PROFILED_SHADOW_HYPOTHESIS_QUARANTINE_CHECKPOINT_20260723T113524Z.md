# Profiled Shadow Hypothesis Quarantine Checkpoint

Timestamp: `2026-07-23T11:35:24Z`
Branch: `codex/strategy-receipt-promotion-20260723`
Implementation commit: `aacb9e3bee03fbc7ff86f0790aca3955e0073f04`
Family status: implementation complete, committed, and pushed

## Outcome

The trainer research boundary can now bind one exact authenticated raw
inference V2 receipt to one freshly revalidated paper/research causal-cost
artifact. The immutable hypothesis uses the decision-time order-book mid
rederived from authenticated best bid and ask evidence. It does not accept a
caller price, an unfinished candle price, a V1 inference receipt, a substituted
snapshot, a substituted decision time, or a different holding horizon.

This is deliberately a quarantined evidence artifact, not an outcome-ready or
runtime-wired artifact. Its hash-bound durability status states that it has no
durable ex-ante commit receipt, no pending-hypothesis index, no portable cost
source closure, and no restart opener. Outcome maturation and calibration input
authority are therefore both false. This prevents a CAS object alone from being
misrepresented as proof that a hypothesis existed before its label was known.

The factory completes upstream revalidation, exact contract construction,
material hashing, bounded canonical serialization, and cost encoding before the
first target-store mutation. Successful construction writes exactly two
content-addressed objects: the final cost contract bytes and the final
hypothesis bytes. Both are read back and byte-compared during result validation.

## Evidence counts

- Production files changed: 2
- Test files changed: 1
- Routes inspected/changed: 0 / 0
- API endpoints compared/changed: 0 / 0
- Screenshots captured: 0
- Builds passed: 0 / 0 (no application build applies to this Python boundary)
- Static/compile command groups passed: 3 / 3
- Services restarted or activated: 0
- Redis reads/writes: 0 / 0
- Exchange/PAPER/live/order paths changed: 0
- Embedded raw V2 fields checked: 64 / 64
- Hypothesis top-level fields checked: 11 / 11
- Ordered causal-cost receipts bound: 4 / 4
- Order-book child receipts bound with roles: 2 / 2
- False downstream-authority fields checked: 18 / 18
- Durability/quarantine status fields checked: 7 / 7
- Target CAS writes on successful construction: 2
- Target CAS writes across two pre-publication rejection cases: 0
- Hypothesis-focused tests passed: 6 / 6
- Combined inference-plus-hypothesis tests passed: 19 / 19
- Python byte-compile checks passed: 3 / 3 files
- Ruff checks passed: 3 / 3 files
- Commit whitespace checks passed: 1 / 1 commit
- Narrow reviewer findings closed inside this boundary: 5 / 5
- Defects remaining in this quarantined family: 0
- Declared blockers before outcome maturation: 2
- Implementation diff: 1,100 insertions, 0 deletions

## Exact bindings and retained invariants

- Only the exact `LocallyAuthenticatedProfiledResearchRawInferenceV2` factory
  type is accepted and freshly revalidated.
- Symbol, durable snapshot identity, source decision time, and the pinned
  900-second label ABI must match the exact causal-cost evidence.
- The four ordered values and four receipt hashes must match their cost
  contract and revalidated receipt objects exactly.
- The decision reference is the exact spread receipt's
  `(best_bid + best_ask) / 2` mid, with the full-spread value rederived and
  checked against its float32 feature scalar.
- Both order-book child receipt roles and hashes are retained; a hash-only
  permutation cannot preserve the contract.
- All 18 downstream authority fields are false, including trainer admission,
  prediction, serving, PAPER, live, execution, outcome maturation, and
  calibration input.
- The artifact is local research evidence and remains explicitly
  non-promotable and runtime-unwired.

## Validation commands

```text
git diff --check
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m py_compile v2/backend/app/services/native_trainer/profiled_research_shadow_hypothesis_v1.py v2/backend/app/services/native_trainer/locally_authenticated_profiled_research_inference_v1.py v2/backend/tests/unit/services/native_trainer/test_profiled_research_shadow_hypothesis_v1.py
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/ruff check v2/backend/app/services/native_trainer/profiled_research_shadow_hypothesis_v1.py v2/backend/app/services/native_trainer/locally_authenticated_profiled_research_inference_v1.py v2/backend/tests/unit/services/native_trainer/test_profiled_research_shadow_hypothesis_v1.py
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_profiled_research_shadow_hypothesis_v1.py
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_profiled_research_shadow_hypothesis_v1.py v2/backend/tests/unit/services/native_trainer/test_locally_authenticated_profiled_research_inference_v1.py
git show --check --oneline aacb9e3bee03fbc7ff86f0790aca3955e0073f04
```

Focused result: `6 passed in 48.86s`.
Combined result: `19 passed in 136.94s`.

## Honest downstream state

This family does not bring the publisher online, create calibrated
profitability, mature outcomes, admit trainer samples, or authorize a signal or
trade. The next family must add both:

1. an append-only, enumerable ex-ante hypothesis commitment/index whose commit
   clock is proven earlier than label availability; and
2. a complete portable cost-source CAS closure with a restart-safe opener and
   fresh revalidation from durable bytes.

Only after both properties are evidenced may a separate outcome-maturation
family consume a committed hypothesis. No future label, mutable current price,
or post-outcome backfill may be used to create or rewrite the hypothesis.

## Files in the implementation commit

- `v2/backend/app/services/native_trainer/locally_authenticated_profiled_research_inference_v1.py`
- `v2/backend/app/services/native_trainer/profiled_research_shadow_hypothesis_v1.py`
- `v2/backend/tests/unit/services/native_trainer/test_profiled_research_shadow_hypothesis_v1.py`
