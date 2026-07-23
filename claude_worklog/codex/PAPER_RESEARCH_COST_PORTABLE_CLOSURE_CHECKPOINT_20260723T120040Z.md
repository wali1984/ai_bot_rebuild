# Paper Research Cost Portable Closure Checkpoint

Timestamp: `2026-07-23T12:00:40Z`
Branch: `codex/strategy-receipt-promotion-20260723`
Implementation commit: `6ffdaff9a7cbd31a403c84f2e5afb87766ef1683`
Family status: implementation complete, committed, and pushed

## Outcome

The paper/research causal-cost boundary can now publish one exact,
restart-safe content-addressed closure containing every immutable object needed
to reopen and freshly revalidate the causal-cost evidence in a new process.
The closure includes the exact 13 original source objects, the final cost
artifact, and the configured-fee Ed25519 public key. Its manifest is published
last and names all 15 prerequisites, so a closure address cannot be issued for
an incomplete inventory.

Opening the closure requires only its CAS root and manifest address. It does
not require the original in-memory cost object, process seal, token identity,
Redis, an exchange connection, or any mutable external state. The opener
rederives and revalidates the notional proof, raw status, aggregate, artifact,
order-book spread, depth impact, mark/funding values, configured-fee signature,
four float32 scalar receipts, and the exact canonical cost and notional
contracts before returning the public result.

Construction completes a full source preflight before the first target-store
mutation. Source objects are copied first, the public key next, and the manifest
last. Numeric bounds and an 8 MiB per-object read limit prevent malformed
metadata from authorizing unbounded reads. Missing objects, substituted keys,
inventory omissions, extra manifest fields, numeric type substitutions,
content-address mismatches, and public-result tampering all fail closed.

This remains an unwired research evidence primitive. It grants no trainer,
calibration, prediction, serving, PAPER, live, exchange, order, deployment, or
runtime authority and does not bring the publisher online.

## Evidence counts

- Production files changed: 1
- Test files changed: 2
- Routes inspected/changed: 0 / 0
- API endpoints compared/changed: 0 / 0
- Screenshots captured: 0
- Builds passed: 0 / 0 (no application build applies to this Python boundary)
- Static/compile command groups passed: 3 / 3
- Services restarted or activated: 0
- Redis reads/writes: 0 / 0
- Exchange/PAPER/live/order paths changed: 0
- Original source CAS objects copied and revalidated: 13 / 13
- Complete restart prerequisites inventoried: 15 / 15
- CAS objects including the manifest: 16
- Manifest fields checked: 23 / 23
- False downstream-authority fields checked: 14 / 14
- Float32 scalar receipts revalidated: 4 / 4
- True fresh-process restart checks passed: 1 / 1
- Missing-prerequisite deletion cases checked: 15 / 15
- Late prewrite rejection cases with zero target writes: 4 / 4
- Portable-closure-focused tests passed: 10 / 10
- Combined causal-cost-plus-closure tests passed: 23 / 23
- Python byte-compile checks passed: 3 / 3 files
- Ruff checks passed: 3 / 3 files
- Commit whitespace checks passed: 1 / 1 commit
- Reviewer implementation defects remaining: 0
- Defects remaining in this portable-closure family: 0
- Downstream blockers before outcome maturation: 1
- Implementation diff: 2,440 insertions, 1 deletion

## Exact bindings and retained invariants

- The manifest has exactly 23 fields and the downstream-authority map has
  exactly 14 boolean fields, all false.
- Schema object counts are fixed at 13 source objects, 15 prerequisites, and 16
  total CAS objects including the manifest.
- The outer public-key fingerprint, trust-anchor identity, and expected source
  revision must match the freshly revalidated configured-fee evidence.
- Every declared object address must match its bounded bytes; the complete
  aggregate size is checked before object reads begin.
- The Ed25519 signature and source material, portable notional proof, raw
  status, aggregate, final artifact, and receipt are reconstructed from durable
  bytes rather than trusted from caller objects.
- Spread, depth impact, mark/funding derivations, four scalar receipts, and the
  canonical cost/notional contracts are rederived and compared exactly.
- Successful publication writes all prerequisites before the manifest. Any
  preflight failure writes zero target objects.
- The closure is research-only, locally verifiable, runtime-unwired, and
  explicitly non-authoritative for training, signals, trades, or execution.

## Validation commands

```text
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m py_compile v2/backend/app/services/native_trainer/paper_research_causal_cost_portable_closure_v1.py v2/backend/tests/unit/services/native_trainer/test_paper_research_causal_cost_portable_closure_v1.py v2/backend/tests/unit/services/native_trainer/test_paper_research_causal_cost_evidence_v1.py
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/ruff check v2/backend/app/services/native_trainer/paper_research_causal_cost_portable_closure_v1.py v2/backend/tests/unit/services/native_trainer/test_paper_research_causal_cost_portable_closure_v1.py v2/backend/tests/unit/services/native_trainer/test_paper_research_causal_cost_evidence_v1.py
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_paper_research_causal_cost_portable_closure_v1.py
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_paper_research_causal_cost_evidence_v1.py v2/backend/tests/unit/services/native_trainer/test_paper_research_causal_cost_portable_closure_v1.py
git diff --check
git show --check --oneline 6ffdaff9a7cbd31a403c84f2e5afb87766ef1683
```

Focused result: `10 passed in 7.12s`.
Combined result: `23 passed in 11.43s`.

## Honest downstream state

The portable source closure removes one of the two blockers declared by the
quarantined shadow-hypothesis family. The single remaining blocker before
outcome maturation is an append-only ex-ante shadow-hypothesis commitment and
pending index with:

1. an internally sampled strict commit clock that precedes label availability;
2. an independently verified post-commit readback receipt;
3. crash-gap recovery and deterministic pending enumeration; and
4. immutable, conflict-detecting, restart-safe hypothesis identity.

No outcome, label, calibration, trainer admission, publisher, signal, or trade
authority may be added until that commitment exists and is proven to have been
made before the canonical label became available.

## Files in the implementation commit

- `v2/backend/app/services/native_trainer/paper_research_causal_cost_portable_closure_v1.py`
- `v2/backend/tests/unit/services/native_trainer/test_paper_research_causal_cost_portable_closure_v1.py`
- `v2/backend/tests/unit/services/native_trainer/test_paper_research_causal_cost_evidence_v1.py`
