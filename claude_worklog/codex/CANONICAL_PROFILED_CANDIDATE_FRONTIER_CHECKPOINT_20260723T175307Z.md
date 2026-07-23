# Canonical Profiled Candidate Frontier Checkpoint — 2026-07-23 17:53:07 UTC

## Resume coordinates

- Worktree: `/tmp/codex-strategy-receipt-promotion`
- Branch: `codex/strategy-receipt-promotion-20260723`
- Parent checkpoint: `b629bfbab45bf41d27df33bff6eb7dd61c9ca399`
- Implementation commit: `a44f1744bfbc7a47e9ca32ba297e5b7e02801c3a`
- Implementation push: local HEAD equals upstream
- Family state: implemented, tested, independently reviewed, committed, pushed
- Services restarted or changed: `0`
- Runtime publisher wiring changed: `0`
- Optimizer/checkpoint/paper/live/exchange authority granted: `0`

## Evidence counts

- Maximum active agents: `2`
- Production files changed: `3`
- Test files changed: `3`
- Implementation files: `6`
- Implementation insertions/deletions: `4,046/2`
- New frontier tests: `9/9` passed
- Modified source-prefix tests: `2/2` passed
- Compile targets: `6/6` passed
- Ruff targets: `6/6` passed
- Diff whitespace checks: passed
- SQLite append-only tables: `7`
- Exact immutable trigger bodies: `14/14` verified
- Denormalized SQL shadow fields: `15/15` independently compared
- Independent blocker families reviewed: `4`
- Independent blockers remaining: `0`
- Page boundary exercised: `128/129` rows over `2` pages
- Maximum representable source rows: `65,536`
- Routes/endpoints/screenshots/builds/services changed: `0/0/0/0/0`
- Defects remaining in this family: `0`

The nine frontier tests were executed in bounded individual or two-test
invocations to avoid retaining multiple heavyweight authenticated trainer
fixtures in one long extension process. Every test declaration passed. No test
failure is being hidden by that process isolation.

## Shipped contract

`profiled_research_canonical_candidate_frontier_ledger_v1.py` now provides one
append-only chain with two event types:

1. `SELECTION` fixes the exact commitment/outcome source pair, receives an
   append receipt, durable independent postcommit receipt, and external head
   anchor, then pages a terminal disposition for every selected commitment.
2. `CANDIDATE` is permitted only when no outcome is due and missing. It binds
   one deterministic key to the exact selection and immutable model binding,
   includes every eligible row for that model ordered by
   `(decision_time, calibration_row_id)`, and receives its own append,
   postcommit, and head receipts.

Terminal accounting explicitly distinguishes:

- finalized calibration eligible;
- finalized calibration ineligible with reason;
- pending because label availability is physically after the cutoff;
- quarantined ex-ante durability failure;
- due outcome missing.

Due/missing persists `WAITING_FOR_FORWARD_COHORT_COMPLETENESS` and consumes no
candidate key. A source-ledger append creates a new immutable source-pair key;
the old waiting selection is never rewritten.

## Point-in-time and crash guarantees

- Both source ledgers expose a public lease and verified historical-prefix row
  reopen API.
- The selection commit must be physically observed after both proposal
  captures.
- Terminal due/pending classification uses the raw, physically sampled
  `postcommit_observed_at`, not a rounded logical timestamp that may still be in
  the future.
- The logical millisecond head time remains separate and is never substituted
  for the physical feature cutoff.
- A durable selection tail can recover from its originally selected historical
  source snapshots even after source ledgers advance.
- A durable candidate tail reopens its event artifact, exact selection/model
  binding, accounting root/pages, and candidate root/pages before it may write
  READY.
- A missing source snapshot, event artifact, candidate root, page, head catalog
  object, database receipt, or binding fails closed.
- Catalog repair is used only for the narrow commit-to-catalog crash gap;
  ordinary integrity verification is strict and never silently repairs missing
  evidence.

## Tamper and capacity closure

- Event, selection, candidate, append, postcommit, and head contracts are
  canonical JSON with exact CAS addresses.
- All seven tables reject update/delete through fourteen exact trigger bodies;
  trigger names alone are not trusted.
- Fifteen duplicated append/post/head SQL fields and all selection/candidate
  shadow fields are independently compared with their canonical contracts.
- The external head catalog makes coordinated database truncation enumerable.
- Accounting and candidate inventories use 128-row pages, prior-page material
  chaining, ordered root descriptors, exact counts, and an 8 MiB object bound.
- The 128/129 boundary proves the second page is mandatory and replayable.
- Every authority bit remains false, including calibration input, optimizer,
  checkpoint mutation, serving, paper, live, risk, allocator, and exchange.

## Focused tests passed

1. complete source pair creates the exact model candidate;
2. same source pair/model is idempotent;
3. due/missing outcome waits and creates zero candidate records;
4. factory, SQL shadow, and recreated-trigger tamper fail closed;
5. durable selection-tail restart recovery;
6. completed integrity reopens selected source-snapshot CAS;
7. candidate-tail recovery requires candidate-root readback;
8. equality boundary, quarantine, and physical-observation cutoff semantics;
9. exact 128/129 candidate-page boundary;
10. commitment public lease/current-prefix/historical-prefix reopen;
11. outcome public lease/current-prefix/historical-prefix reopen.

## Mandatory scope discovered in parallel

The bounded Moralis/liquidation audit changed no files or services:

- Moralis service active, `NRestarts=0`, but health is
  `ISOLATED_BY_POLICY/GRAY`; feature keys `0`; verified smart wallets `0`;
  daily CU `32,530/55,000`; monthly CU `158,440/2,000,000`.
- Moralis has semantic producers for only `3/7` optional trainer ABI slots,
  zero authenticated exchange-wallet identities, a hard consumer/receipt fence,
  and no retained-artifact resolver. The CU scheduler/rate ledger is healthy and
  should be preserved.
- The active liquidation service publishes `161 symbols x 5 timeframes = 805`
  payloads, but it clusters already-forced liquidation executions. It is not a
  prospective position liquidation-level engine.
- Prospective liquidation engines found: `0`. Moralis cannot supply futures
  entry/leverage/margin distributions. Without such evidence, prospective
  outputs must be labeled estimates, never “real observed liquidation levels.”
- Existing liquidation ABI slots have forced-event semantics. Prospective
  estimates require versioned features and retraining; silent replacement would
  corrupt checkpoint semantics.

## Exact next families

1. Build the immutable validation-role/V3 admission receipt over this canonical
   candidate. It must assign roles without static sample thresholds, preserve
   all PIT clocks, remain non-authorizing until replay closure passes, and leave
   V1/V2 paths unchanged.
2. Integrate that admission receipt into the profiled publisher, checkpoint
   evidence, and coordinator; run final regression before any held-service
   release.
3. Repair Moralis producer authenticity/retained-artifact consumption for the
   three features that have real semantics, keep absent/unproven slots masked,
   preserve the current rate ledger, and keep CoinAPI optional.
4. Add a separately versioned prospective liquidation-estimate engine and
   trainer bridge with explicit `event_time`, `ingested_at`, `available_at`,
   `feature_cutoff`, source coverage, uncertainty, staleness adaptation, and
   postcommit receipts. Do not relabel forced-liquidation clusters as
   prospective levels.
5. Only after all above is complete: final regression, bounded service release,
   runtime evidence counts, and documentation updates. Website/iOS/GPU scope
   remains deferred per operator instruction.

## Verification and publication commands

```bash
python -m py_compile <six changed Python files>
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/ruff check <six changed Python files>
git diff --check

/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q \
  <each of the nine named frontier tests above>

/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q \
  test_profiled_research_shadow_hypothesis_commitment_v1.py::test_inventory_snapshot_replays_current_head_and_remains_non_authoritative \
  test_profiled_research_finalized_outcome_ledger_v1.py::test_inventory_snapshot_replays_current_head_and_remains_non_authoritative

git add <six implementation/test files>
git diff --cached --check
git commit -m "trainer: seal canonical profiled candidate frontier"
git push origin codex/strategy-receipt-promotion-20260723
```
