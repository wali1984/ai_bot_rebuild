# Profiled Shadow Ex-Ante Commitment Checkpoint

Timestamp: `2026-07-23T12:56:00Z`
Branch: `codex/strategy-receipt-promotion-20260723`
Implementation commit: `8c0a4c21a7fabb4c1dfc7b44bd90f80984ca1717`
Family status: implementation complete, committed, pushed, and regression-clean

## Outcome

The exact factory-built profiled research shadow hypothesis and its complete
portable causal-cost closure can now be committed to an append-only SQLite
ledger before the canonical counterfactual label is available. The first
transaction atomically persists the hypothesis binding, pending index, append
receipt, and hash-chain link. A separately reopened transaction records the
post-commit readback receipt and chained head anchor. A dedicated enumerable
content-addressed head-anchor catalog makes complete SQLite suffix truncation
detectable and supports deterministic recovery of the database-to-catalog
crash gap.

Raw microsecond clock observations are sealed separately from conservative
millisecond logical ordering clocks. A hypothesis is eligible for the pending
index only when the post-commit raw observation is strictly later than the raw
commit observation and strictly earlier than label availability. Raw clock
ties, rollback, source-clock skew, exact label-boundary observations, and late
observations fail closed or remain durably quarantined. A logical clock bump
cannot manufacture ex-ante evidence.

Public database, hypothesis CAS, portable-cost CAS, and head-catalog reads are
covered by one stable reader lease. The sanctioned writer is excluded for the
whole snapshot. Caller-owned writer leases support constructor-bound and
per-call operation without self-contention, retain before/after validation for
final DB/CAS/catalog readback, and fall back to the shared reader lease after
release.

All SQLite object SQL is pinned exactly. Initialization, fixed metadata, and
application/user identifiers commit atomically. Rows reject update/delete,
resource bounds cover database pages and aggregate JSON, exact canonical
receipts are freshly reconstructed, and restart reads reopen and validate the
hypothesis and complete portable cost closure from durable bytes.

This family remains an unwired research primitive. It imports into no runtime
module and grants no outcome, calibration, trainer, publisher, prediction,
serving, PAPER, live, exchange, deployment, order, or execution authority.

## Evidence counts

- Production files changed: 2
- Test files changed: 1
- Public ledger routes inspected and covered: 5 / 5
- HTTP/API endpoints compared or changed: 0 / 0
- Screenshots captured: 0
- Application builds applicable: 0
- Static/compile quality gates passed: 2 / 2
- Services restarted or activated: 0
- Redis reads/writes: 0 / 0
- Exchange/PAPER/live/order paths changed: 0
- Runtime imports of the new commitment module: 0
- SQLite tables checked: 6 / 6
- SQLite persisted columns checked: 74 / 74
- SQLite indexes checked: 2 / 2
- SQLite immutability triggers checked: 12 / 12
- Exact contract/binding/authority/result field declarations checked: 83
- Causal ledger clock fields distinguished: 7 / 7
- False downstream-authority fields checked: 18 / 18
- Crash gaps covered: 2 / 2
- Fresh-process restart checks passed: 1 / 1
- Reader/writer lease boundaries independently reviewed: 3 / 3
- Constructor-bound external writer lease cases passed: 1 / 1
- Per-call external writer lease cases passed: 1 / 1
- Focused commitment test functions: 20
- Focused commitment test cases passed: 22 / 22
- Upstream local-inference regression cases passed: 13 / 13
- Python byte-compile checks passed: 3 / 3 files
- Ruff checks passed: 3 / 3 files
- Commit whitespace checks passed: 1 / 1 commit
- Reviewer defects found and fixed in final pass: 1 / 1
- Reviewer defects remaining: 0
- Defects remaining in this family: 0
- Immediate downstream blockers before outcome maturation: 0
- Known immediate downstream family now queued: 1
- Implementation diff: 4,916 insertions, 1 deletion

## Five public ledger routes

1. `commit_hypothesis`
2. `recover_pending_postcommit_readbacks`
3. `verify_integrity`
4. `open_committed_hypothesis`
5. `list_pending_hypotheses`

## Seven causal clock fields

1. `decision_time`
2. `hypothesis_generated_at`
3. `label_earliest_available_at`
4. `commit_observed_at` (raw microsecond observation)
5. `commit_prepared_at` (logical millisecond ordering clock)
6. `postcommit_observed_at` (raw microsecond observation)
7. `postcommit_readback_at` (logical millisecond ordering clock)

The raw clocks establish observed causality. The logical clocks provide strict,
canonical ledger order and never substitute for raw ex-ante proof.

## Retained invariants

- The public commit API accepts no caller clock, label, outcome, price, or
  return value.
- The exact hypothesis, its CAS address, its portable cost-closure address,
  raw-inference binding, cost artifact, decision reference, and immutable
  identity are cross-bound before append.
- `hypothesis_generated_at <= commit_observed_at < label_earliest_available_at`
  is required before the append can be prepared.
- Pending eligibility additionally requires
  `commit_observed_at < postcommit_observed_at < label_earliest_available_at`.
- A raw post-commit tie, rollback, or late observation is durably recorded with
  `ex_ante_durability_verified = 0` and excluded from pending enumeration.
- Commit, append, post-commit, pending-index, and head-anchor JSON are canonical,
  hash-bound, and freshly reconstructed during every integrity read.
- The SQLite chain and independently enumerable head-anchor CAS must have exact
  membership; silent tail deletion fails closed.
- Reader stability spans SQLite, both source CAS closures, and the head catalog.
- The result object is factory-sealed and reopens its durable binding before an
  authority/status property can be read.
- All 18 downstream-authority values remain exact booleans set to `false`.

## Validation commands

```text
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m py_compile v2/backend/app/services/native_trainer/profiled_research_shadow_hypothesis_commitment_v1.py v2/backend/app/services/native_trainer/locally_authenticated_profiled_research_inference_v1.py v2/backend/tests/unit/services/native_trainer/test_profiled_research_shadow_hypothesis_commitment_v1.py
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/ruff check v2/backend/app/services/native_trainer/profiled_research_shadow_hypothesis_commitment_v1.py v2/backend/app/services/native_trainer/locally_authenticated_profiled_research_inference_v1.py v2/backend/tests/unit/services/native_trainer/test_profiled_research_shadow_hypothesis_commitment_v1.py
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/pytest -q v2/backend/tests/unit/services/native_trainer/test_profiled_research_shadow_hypothesis_commitment_v1.py
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/pytest -q v2/backend/tests/unit/services/native_trainer/test_locally_authenticated_profiled_research_inference_v1.py
git diff --check
git diff --cached --check
git show --check --oneline 8c0a4c21a7fabb4c1dfc7b44bd90f80984ca1717
```

Focused result: `22 passed in 193.83s`.

Upstream inference result: `13 passed in 94.49s`.

Final external-writer-lease reviewer result: `2 passed in 31.03s`; three lease
boundaries inspected; zero concrete defects remaining.

## Honest downstream state

The durable ex-ante commitment and pending-index blocker is closed. No label or
outcome has been consumed, and this module is not wired into the trainer or any
service. The next family is the finalized-label outcome-maturation contract:
it must consume only hypotheses with valid ex-ante receipts, wait until the
canonical label is actually final and available, preserve point-in-time
lineage, derive calibration evidence without future leakage, and continue to
grant zero publisher/trainer/trading authority until that evidence is itself
durably proven.

Publisher activation remains blocked on that next family and its final
regression. This checkpoint does not claim the trainer publisher is online.

## Files in the implementation commit

- `v2/backend/app/services/native_trainer/locally_authenticated_profiled_research_inference_v1.py`
- `v2/backend/app/services/native_trainer/profiled_research_shadow_hypothesis_commitment_v1.py`
- `v2/backend/tests/unit/services/native_trainer/test_profiled_research_shadow_hypothesis_commitment_v1.py`
