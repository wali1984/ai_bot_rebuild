# CG-F063 (P0): CG-F056 reconciliation destroys legitimate positions

Owner: Codex paper-loop lane. Independent adversarial verification (Claude) found the
CG-F056 fix INTRODUCED a destructive accounting defect. Paper-only; live BLOCKED.

## The defect
`_paper_reconcile_ledger_to_accepted_fill_proofs` (v2_trade_management_paper_loop.py:33438-33566)
treats a reachable-but-EMPTY `v2:paper:open_position_fill_proofs` as authoritative 'zero
legitimate positions' and drops every open position. `_paper_accepted_fill_proof_source`
(:33123-33228) returns READY/rows=[] on missing/empty (MISSING->READY in 113b613c5d). The
rail is brand-new + unbackfilled, so pre-existing legitimate positions are wiped as
UNPROVED_PHANTOM_POSITION.

## Live proof
5 receipts under `v2:paper:position_fill_reconciliation:receipts:*` (AAVE, BASED, PARTI,
BSB) wiped 01:00-01:25Z, ~$248 margin released, no close event, no PnL.

## Fix (pick one) + regression test
(a) one-time backfill: seed `open_position_fill_proofs` from each open position's legacy
`paper:accepted_fills` match BEFORE the scrub's first authoritative run; OR
(b) require corroboration: only treat empty-as-authoritative when `existing_ledger` also
has zero positions, else fail-closed (mirror the 'malformed' branch).
ADD a cold-start regression test: non-empty `v2:paper:positions` + empty
`open_position_fill_proofs` must NOT wipe legitimate positions.

## Keep (verified sound)
non-empty quarantine reasons (:2842-2874); reconstruction-from-proof-only; scrub-before-
reconstruct order (:45897 < :51054); OPEN_POSITION_SOURCE_FILL_PROOF_MISSING fail-closed (:33972).

## Why it matters now
21 clean directional candidates (long+short, conf 1.0, resolved rd_dec_*/dec_*, 0 gate
reasons) are blocked SOLELY by the reservation cascade tied to this churn. Fixing CG-F063
(so legitimate positions persist proof-backed and only genuine invalid-admission fills are
dropped) stabilizes the reservation -> the 21 candidates fill -> first natural lifecycle.
