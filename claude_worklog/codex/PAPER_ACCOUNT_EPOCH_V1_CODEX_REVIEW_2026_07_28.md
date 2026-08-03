# PaperAccountEpochV1 Codex review

Reviewed UTC: 2026-07-28T04:20:25.605120Z

Reviewed commit: `bad88d5409dc33c7d30a191bde235a12fe1e7d7e`

Decision: `BLOCK`

Safety: read-only against production; isolated nominal tests only; rotation not executed

## Result

The prestaged rotation must not be executed or wired into an operator path. Its
nominal DB-15 suite passes 13/13 and the production dry preflight correctly
returns `BLOCKED_RESET_PRECONDITION`, but the executable path is not fail-closed
or atomic enough to reset paper-account state safely.

## Blocking findings

1. `rotate(execute=True)` mutates the epoch counter and archive key before the
   Lua guard. If the guard rejects, the function returns
   `state_mutated=false` even though both keys changed. The adversarial in-memory
   probe observed `v2:paper:account_epoch:counter` and
   `v2:paper:account_epoch:archive:s1` after `BLOCKED_ATOMIC_GUARD`.
2. Critical Redis JSON decode failure is converted to absence. A malformed
   `v2:paper:positions` payload therefore produced preflight `PASS` when the
   other seeded predicates were valid. Missing, malformed, wrong-container and
   initialized-empty states must be distinct for every destructive input.
3. `pending_reservations` is hard-coded to zero and does not consume an
   authoritative reservation/account-margin source. A non-empty seeded
   `v2:paper:reservations` value was reported as `actual=0, pass=true`.
4. Archive readback verifies the closed-trade hash but only the accepted-fill
   count and no position hash. Same-count accepted-fill mutation and position
   identity mutation both returned `(true, "ok")`.
5. `expected_previous_session_id` does not compare with the current session. A
   mismatched predecessor returned `DRY_RUN_OK` instead of failing closed.
6. The rotation writes the new epoch pointer and portfolio face but does not
   update `v2:paper:session`. The paper loop and canonical PnL/adaptive consumers
   still use `v2:paper:session`, creating a split-brain session identity if the
   executable path is used before writer/reader cutover.
7. The manifest is described as immutable but is written with unconditional
   `SET`, outside the Lua transaction, without a persisted readback/hash check.
   A racing or repeated request can overwrite it, and a later Lua failure leaves
   a misleading archive artifact.

## Required repair

- Keep execution disabled until all paper writers and readers consume one
  atomically updated session identity.
- Parse every critical source with explicit `MISSING`, `MALFORMED`,
  `WRONG_CONTAINER`, and `READY` states; only an authenticated initialized-empty
  state can satisfy the gate.
- Bind authoritative pending-reservation, reserved-margin, proof-manifest,
  accounting, fill, position and close inputs into the atomic compare-and-set.
- Move counter allocation, immutable archive creation, pointer/session update,
  clean face creation, idempotency and receipt creation into one atomic operation
  or correctly report every partial mutation with a recoverable receipt.
- Verify accepted-fill, position, portfolio, session and closed-trade hashes and
  counts before commit and after persisted archive readback.
- Reject predecessor mismatch and make idempotency generation-specific so a
  later legitimate epoch is not treated as replay of the first rotation.
- Add adversarial regression fixtures for all seven findings before re-review.

## Evidence

```text
nominal isolated suite: 13 passed
production preflight: BLOCKED_RESET_PRECONDITION; state_mutated=false
production failing predicates:
  unresolved_position_proof_rows=16
  reserved_margin_usd=null
  proof_store_initialized=null
  proof_store_backfill_complete=null

adversarial probe:
  malformed_positions_preflight_status=PASS
  pending reservation actual=0 pass=true despite non-empty reservation source
  accepted_fill_hash_verified=(true, ok) after same-count content mutation
  position_hash_verified=(true, ok) after identity mutation
  mismatched_expected_predecessor=DRY_RUN_OK
  blocked atomic result=BLOCKED_ATOMIC_GUARD/state_mutated=false
  keys mutated before rejected guard=archive:s1, account_epoch:counter
```

Source hashes:

```text
epoch.py=a2868baa243dcb73f5a11c70929b0518bda02dc417fc6e75c0cfe88e0e8241e8
test_paper_epoch_rotation.py=cec3e89fd1e47d4ec75588cd951843fa6271650bc777b2597fc1dc3e0b2068cb
paper_epoch_preflight.py=374ad8633893bbe415a38b656aacb0113d12ee0562b6d1f4a29fd9779d1797bf
paper_epoch_rotate.py=a5bc8eaa9bc4d2f6498b5d731a128712eacff1086682e14a1f5362d0d2aec7b4
```

`PAPER_ACCOUNT_EPOCH_V1_CODEX_BLOCK`
