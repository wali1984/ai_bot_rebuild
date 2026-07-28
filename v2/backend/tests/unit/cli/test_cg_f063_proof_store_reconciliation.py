"""Regression fixtures for CG-F063.

CG-F063 defect: proof-position reconciliation treated a reachable-but-EMPTY /
uninitialized ``open_position_fill_proofs`` store as authoritative "zero
legitimate positions" and WIPED real open positions (confirmed incident: 5
positions / $248.32 margin released, no close/PnL created to justify it).

These fixtures encode the REQUIRED post-fix contract per the operator spec:

1. An absent/uninitialized proof store is NEVER authoritative for "zero
   positions" -- it must fail closed and retain every open position.
2. Only a genuinely-empty, ATOMICALLY INITIALIZED proof set (backed by a
   completed manifest) is authoritative for "zero legitimate positions".
3. A backfill mechanism must be able to (re)populate the proof rail from
   durable accepted-fill/lifecycle evidence, binding identity + accounting
   fields, and sealing a hashed manifest.
4. Only positively-corroborated-invalid ("phantom") positions are ever
   removed; removal must be idempotent, must release margin exactly once,
   must never mutate wallet balance, must never fabricate a close, and must
   conserve total margin (released + retained == pre-reconciliation total).
5. The rules must be side-symmetric (long == short) and must survive a
   simulated process restart when durable proof already exists.
6. A hash-bound, admitted reduce-only close transition must advance the
   durable proof to the coherent remaining position.  A changed quantity,
   notional, or margin after that transition is not positive phantom evidence.

Paper-only. Live trading stays BLOCKED. This file is test-only: it does not
modify ``v2_trade_management_paper_loop.py`` (owned by Codex) or any hook.

Where the fix is not (yet) fully landed, assertions target OBSERVABLE
behavior (positions retained/removed, margin released, wallet/close state)
through the two production entry points named in the CG-F063 ticket:
``_paper_accepted_fill_proof_source`` and
``_paper_reconcile_ledger_to_accepted_fill_proofs`` (plus the backfill
builder ``_paper_build_open_position_fill_proof_backfill`` and manifest
builder ``_paper_open_position_fill_proof_manifest`` that back them), rather
than on exact internal status-string spelling wherever that spelling was
uncertain at fixture-authoring time. Comments flag those spots so Codex can
align exact names.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop

PROOF_KEY = paper_loop.PAPER_OPEN_POSITION_FILL_PROOFS_REDIS_KEY
MANIFEST_KEY = paper_loop.PAPER_OPEN_POSITION_FILL_PROOF_MANIFEST_REDIS_KEY


class _FakeRedis:
    """Minimal redis stand-in mirroring the pattern used across this test
    package's existing paper-loop tests (see ``_FakeRedis`` in
    ``test_v2_trade_management_paper_loop.py``): a dict-backed ``get``/``set``
    with ``strlen`` for the payload-size guard. A key that was never placed
    in ``payloads`` reproduces a genuinely absent/uninitialized Redis key
    (``GET`` returns ``nil``); a key explicitly set to ``[]``/a manifest dict
    reproduces an atomically-initialized store.
    """

    def __init__(self, payloads: dict[str, Any]):
        import json as _json

        self.payloads = {
            key: value if isinstance(value, str) else _json.dumps(value, default=str)
            for key, value in payloads.items()
        }

    def get(self, key: str):
        return self.payloads.get(key)

    def set(self, key: str, value: str, ex: int | None = None):
        del ex
        self.payloads[key] = value
        return True

    def strlen(self, key: str) -> int:
        value = self.payloads.get(key)
        if value is None:
            return 0
        return len(value.encode("utf-8") if isinstance(value, str) else value)


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _alternating_sides(count: int) -> list[str]:
    sides = ["long", "short"]
    return [sides[i % 2] for i in range(count)]


def _make_fill_position(
    symbol: str,
    side: str,
    index: int,
    *,
    quantity: float = 0.5,
    price: float = 100.0,
    leverage: float = 1.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a matched (fill, position) pair with every field the current
    production validators (``_paper_build_open_position_fill_proof`` /
    ``_paper_open_position_fill_proof_reasons``) require for a clean proof.
    """

    fill_id = f"fill-{symbol.lower()}-{index}"
    prediction_id = f"pred-{symbol.lower()}-{index}"
    position_id = f"paper-pos-{symbol.lower()}-{index}"
    position_generation_id = _hash(f"gen-{fill_id}")
    margin = round(quantity * price / leverage, 8)
    notional = round(quantity * price, 8)
    fill = {
        "fill_id": fill_id,
        "ledger_row_id": fill_id,
        "position_id": position_id,
        "position_generation_id": position_generation_id,
        "checkpoint_id": f"checkpoint-{index}",
        "prediction_id": prediction_id,
        "signal_id": f"sig-{fill_id}",
        "intent_id": f"intent-{fill_id}",
        "orchestrator_decision_id": f"orch-{fill_id}",
        "risk_decision_id": f"risk-{fill_id}",
        "allocation_id": f"alloc-{fill_id}",
        "adaptive_policy_action_id": f"action-{fill_id}",
        "symbol": symbol,
        "timeframe": "5m",
        "side": side,
        "quantity": quantity,
        "fill_price": price,
        "gross_notional_usd": notional,
        "effective_leverage": leverage,
        "allocated_margin_usd": margin,
        "paper_final_admission_status": "PASS",
        "paper_final_admission_contract": {"status": "PASS"},
        "paper_final_admission_receipt_hash": _hash(f"receipt-{fill_id}"),
        "paper_final_admission_bound_material_hash": _hash(f"bound-{fill_id}"),
        "paper_persisted_ledger_contract_hash": _hash(f"ledger-{fill_id}"),
        "paper_cycle_reservation_commit_receipt_hash": _hash(f"reservation-{fill_id}"),
        "adaptive_policy_action_sha256": _hash(f"policy-{fill_id}"),
        "adaptive_paper_policy_authorization_sha256": _hash(f"auth-{fill_id}"),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    position = {
        "position_id": position_id,
        "position_generation_id": position_generation_id,
        "entry_fill_id": fill_id,
        "source_fill_ids": [fill_id],
        "checkpoint_id": f"checkpoint-{index}",
        "prediction_id": prediction_id,
        "signal_id": f"sig-{fill_id}",
        "symbol": symbol,
        "timeframe": "5m",
        "side": side,
        "net_quantity": quantity,
        "avg_entry_price": price,
        "gross_notional_usd": notional,
        "effective_leverage": leverage,
        "allocated_margin_usd": margin,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    return fill, position


def _sealed_proof(fill: dict[str, Any], position: dict[str, Any], *, generated_utc: str) -> dict[str, Any]:
    proof, reasons = paper_loop._paper_build_open_position_fill_proof(  # noqa: SLF001
        fill, position, generated_utc=generated_utc
    )
    assert reasons == [], f"fixture proof failed to seal: {reasons}"
    assert proof is not None
    return proof


def _five_valid_triples(prefix: str = "SYM") -> list[tuple[dict, dict, dict]]:
    """Five distinct, fully-valid (fill, position, proof) triples, sides
    alternating long/short/long/short/long -- the exact "5 legitimate open
    positions" shape from the CG-F063 incident (5 positions / $248.32
    margin wiped).
    """

    triples = []
    for i, side in enumerate(_alternating_sides(5), start=1):
        fill, position = _make_fill_position(f"{prefix}{i}USDT", side, i)
        proof = _sealed_proof(fill, position, generated_utc="2026-07-28T00:00:00Z")
        triples.append((fill, position, proof))
    return triples


def _ledger_from_positions(positions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "open_positions": [dict(p) for p in positions],
        "positions_by_symbol": {p["symbol"]: dict(p) for p in positions},
        "open_position_count": len(positions),
    }


def _proof_source_from_store(
    proofs: list[dict[str, Any]] | None,
    manifest: dict[str, Any] | None,
) -> dict[str, Any]:
    payloads: dict[str, Any] = {}
    if proofs is not None:
        payloads[PROOF_KEY] = proofs
    if manifest is not None:
        payloads[MANIFEST_KEY] = manifest
    redis_client = _FakeRedis(payloads)
    return paper_loop._paper_accepted_fill_proof_source(redis_client)  # noqa: SLF001


def _manifest_for(
    proofs: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    *,
    generated_utc: str = "2026-07-28T00:00:00Z",
) -> dict[str, Any]:
    bindings = [
        {"position_id": position.get("position_id"), "proof_id": proof.get("proof_id")}
        for position, proof in zip(positions, proofs)
    ]
    return paper_loop._paper_open_position_fill_proof_manifest(  # noqa: SLF001
        proofs, positions, generated_utc=generated_utc, bindings=bindings
    )


# ---------------------------------------------------------------------------
# 1. The core incident: uninitialized store + 5 legit positions must NOT wipe.
# ---------------------------------------------------------------------------


def test_five_legit_positions_empty_uninitialized_proof_store_retained_all() -> None:
    """Acceptance rule: a reachable-but-EMPTY/uninitialized proof store (the
    proof key was never written -- not even an explicit ``[]``) is NOT
    authoritative evidence of "zero legitimate positions". All 5 real open
    positions must be retained, the reconciliation must classify this as an
    uninitialized proof store and fail closed, and it must release no
    used/reserved margin, create no close, and mutate no wallet balance.
    This is the exact CG-F063 incident shape (5 positions / $248.32 margin).
    """

    triples = _five_valid_triples()
    positions = [position for _, position, _ in triples]
    ledger = _ledger_from_positions(positions)

    # The proof key (and its manifest) were never written at all -- this is
    # the "reachable Redis, absent key" case, distinct from an explicit [].
    redis_client = _FakeRedis({})
    proof_source = paper_loop._paper_accepted_fill_proof_source(redis_client)  # noqa: SLF001

    reconciled, receipt = paper_loop._paper_reconcile_ledger_to_accepted_fill_proofs(  # noqa: SLF001
        ledger,
        proof_source,
        generated_utc="2026-07-28T00:00:01Z",
    )

    # No wipe: all 5 positions survive reconciliation.
    assert len(paper_loop._paper_open_position_rows(reconciled)) == 5  # noqa: SLF001
    assert receipt["retained_position_count"] == 5
    assert receipt["phantom_position_count"] == 0
    assert receipt["unresolved_position_count"] == 5

    # No economic side effects from an unresolved/uninitialized store.
    assert receipt["used_margin_released_usd"] == 0.0
    assert receipt["reserved_margin_released_usd"] == 0.0
    assert receipt["wallet_balance_mutation_usd"] == 0.0
    assert receipt.get("wallet_mutation_allowed") is False

    # No close fabricated: reconciliation must not introduce/alter close rows.
    assert reconciled.get("closed_trades", []) == ledger.get("closed_trades", [])
    assert reconciled.get("closes", []) == ledger.get("closes", [])

    # It must fail closed (not silently PASS as a clean "no proofs needed",
    # and not REPAIRED as though a real wipe were justified).
    assert receipt["status"] not in ("PASS", "REPAIRED")

    # Classification: expect an explicit uninitialized-store marker somewhere
    # observable (source status/initialization_state or the receipt's
    # rejection reasons). Exact name uncertain at fixture-authoring time --
    # Codex should align this to a single canonical
    # "PROOF_STORE_UNINITIALIZED"-style status; asserting on the substring
    # keeps this fixture resilient to the final exact spelling.
    observed_markers = " ".join(
        [
            str(proof_source.get("status") or ""),
            str(proof_source.get("initialization_state") or ""),
            " ".join(str(r) for r in proof_source.get("rejection_reasons") or []),
            " ".join(str(r) for r in receipt.get("rejection_reasons") or []),
        ]
    )
    assert "UNINITIALIZED" in observed_markers, (
        "expected an explicit uninitialized-proof-store classification "
        f"somewhere in source/receipt; observed={observed_markers!r}"
    )


# ---------------------------------------------------------------------------
# 2. Backfill seeds proofs from durable evidence.
# ---------------------------------------------------------------------------


def test_backfill_creates_five_valid_proof_bindings() -> None:
    """Acceptance rule: a backfill step seeds proofs for open positions from
    durable accepted-fill evidence, binding symbol/side/quantity/entry/
    notional/margin/prediction_id/checkpoint_id/fill_id per position, and
    emits a hashed backfill manifest (schema-versioned, sha256-sealed) with
    one binding per resolved position and zero unresolved positions.
    """

    positions: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []
    for i, side in enumerate(_alternating_sides(5), start=1):
        fill, position = _make_fill_position(f"BF{i}USDT", side, 100 + i)
        fills.append(fill)
        positions.append(position)

    proofs, manifest = paper_loop._paper_build_open_position_fill_proof_backfill(  # noqa: SLF001
        positions,
        fills,
        [],
        [],
        generated_utc="2026-07-28T02:00:00Z",
    )

    assert len(proofs) == 5
    assert manifest["completed"] is True
    assert manifest["unresolved_position_count"] == 0
    assert manifest["corroborated_invalid_position_count"] == 0
    assert manifest["schema_version"] == (
        paper_loop.PAPER_OPEN_POSITION_FILL_PROOF_MANIFEST_SCHEMA_VERSION
    )
    assert paper_loop._paper_valid_sha256(manifest["manifest_sha256"])  # noqa: SLF001
    assert len(manifest["bindings"]) == 5

    proofs_by_position = {proof["position_id"]: proof for proof in proofs}
    for position, fill in zip(positions, fills):
        proof = proofs_by_position[position["position_id"]]
        assert proof["symbol"] == position["symbol"]
        assert proof["side"] == position["side"]
        assert proof["quantity"] == pytest.approx(position["net_quantity"])
        assert proof["fill_price"] == pytest.approx(position["avg_entry_price"])
        assert proof["gross_notional_usd"] == pytest.approx(position["gross_notional_usd"])
        assert proof["allocated_margin_usd"] == pytest.approx(position["allocated_margin_usd"])
        assert proof["prediction_id"] == position["prediction_id"]
        assert proof["checkpoint_id"] == position["checkpoint_id"]
        assert proof["fill_id"] == fill["fill_id"]

    bindings_by_position = {b["position_id"]: b for b in manifest["bindings"]}
    for position in positions:
        binding = bindings_by_position[position["position_id"]]
        proof = proofs_by_position[position["position_id"]]
        assert binding["proof_id"] == proof["proof_id"]
        assert binding["fill_id"] == proof["fill_id"]
        assert binding["prediction_id"] == proof["prediction_id"]
        assert binding["checkpoint_id"] == proof["checkpoint_id"]


# ---------------------------------------------------------------------------
# 3. Backfill + reconciliation is idempotent.
# ---------------------------------------------------------------------------


def test_backfill_then_reconciliation_idempotent() -> None:
    """Acceptance rule: running backfill and then reconciliation twice (a
    second cycle observing the same durable proof state) yields identical
    outcomes -- no duplicate margin release, no duplicate proof rows, no
    duplicate close, no wallet mutation on either pass.
    """

    positions: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []
    for i, side in enumerate(_alternating_sides(5), start=1):
        fill, position = _make_fill_position(f"IDEMP{i}USDT", side, 200 + i)
        fills.append(fill)
        positions.append(position)

    proofs, manifest = paper_loop._paper_build_open_position_fill_proof_backfill(  # noqa: SLF001
        positions, fills, [], [], generated_utc="2026-07-28T03:00:00Z"
    )
    assert len(proofs) == 5

    # No duplicate proof rows within a single backfill.
    proof_ids = [proof["proof_id"] for proof in proofs]
    assert len(set(proof_ids)) == len(proof_ids) == 5

    proof_source = _proof_source_from_store(proofs, manifest)
    ledger = _ledger_from_positions(positions)

    reconciled_1, receipt_1 = paper_loop._paper_reconcile_ledger_to_accepted_fill_proofs(  # noqa: SLF001
        ledger, proof_source, generated_utc="2026-07-28T03:00:01Z"
    )
    reconciled_2, receipt_2 = paper_loop._paper_reconcile_ledger_to_accepted_fill_proofs(  # noqa: SLF001
        reconciled_1, proof_source, generated_utc="2026-07-28T03:00:02Z"
    )

    for receipt in (receipt_1, receipt_2):
        assert receipt["status"] == "PASS"
        assert receipt["phantom_position_count"] == 0
        assert receipt["retained_position_count"] == 5
        assert receipt["used_margin_released_usd"] == 0.0
        assert receipt["wallet_balance_mutation_usd"] == 0.0

    assert len(paper_loop._paper_open_position_rows(reconciled_1)) == 5  # noqa: SLF001
    assert len(paper_loop._paper_open_position_rows(reconciled_2)) == 5  # noqa: SLF001
    assert reconciled_1.get("closed_trades", []) == reconciled_2.get("closed_trades", [])

    # Re-running the backfill against its own prior output must not mint new
    # proofs (existing durable proofs are carried, not re-sealed/duplicated).
    proofs_again, _manifest_again = paper_loop._paper_build_open_position_fill_proof_backfill(  # noqa: SLF001
        positions, fills, [], proofs, generated_utc="2026-07-28T03:00:03Z"
    )
    assert len(proofs_again) == 5
    assert {p["proof_id"] for p in proofs_again} == {p["proof_id"] for p in proofs}


# ---------------------------------------------------------------------------
# 4. Only a corroborated phantom is removed; valid siblings survive.
# ---------------------------------------------------------------------------


def test_one_corroborated_phantom_among_valid_removed_only_phantom() -> None:
    """Acceptance rule: given 4 valid positions and 1 genuinely invalid
    position (its entry fill is explicitly quarantined with non-empty exact
    reasons), reconciliation removes ONLY the phantom; the 4 valid positions
    are retained unchanged.
    """

    valid_positions: list[dict[str, Any]] = []
    valid_fills: list[dict[str, Any]] = []
    for i, side in enumerate(_alternating_sides(4), start=1):
        fill, position = _make_fill_position(f"OK{i}USDT", side, 300 + i)
        valid_fills.append(fill)
        valid_positions.append(position)

    invalid_fill, invalid_position = _make_fill_position("BADUSDT", "short", 999)
    quarantine_row = {
        "fill_id": invalid_fill["fill_id"],
        "position_id": invalid_position["position_id"],
        "prediction_id": invalid_position["prediction_id"],
        "accepted_fill_quarantined": True,
        "accepted_fill_quarantine_reasons": [
            "OPEN_POSITION_FILL_PROOF_FINAL_ADMISSION_NOT_PASS"
        ],
    }

    mixed_positions = valid_positions + [invalid_position]
    proofs, manifest = paper_loop._paper_build_open_position_fill_proof_backfill(  # noqa: SLF001
        mixed_positions,
        valid_fills,
        [quarantine_row],
        [],
        generated_utc="2026-07-28T04:00:00Z",
    )
    assert len(proofs) == 4
    assert manifest["corroborated_invalid_position_count"] == 1

    proof_source = _proof_source_from_store(proofs, manifest)
    ledger = _ledger_from_positions(mixed_positions)

    reconciled, receipt = paper_loop._paper_reconcile_ledger_to_accepted_fill_proofs(  # noqa: SLF001
        ledger, proof_source, generated_utc="2026-07-28T04:00:01Z"
    )

    assert receipt["retained_position_count"] == 4
    assert receipt["phantom_position_count"] == 1
    retained_symbols = {
        row["symbol"] for row in paper_loop._paper_open_position_rows(reconciled)  # noqa: SLF001
    }
    assert retained_symbols == {p["symbol"] for p in valid_positions}
    assert "BADUSDT" not in retained_symbols
    assert receipt["phantom_positions"][0]["symbol"] == "BADUSDT"


# ---------------------------------------------------------------------------
# 5. Margin release for a removed position happens exactly once.
# ---------------------------------------------------------------------------


def test_no_duplicate_margin_release() -> None:
    """Acceptance rule: a position removed once releases its allocated
    margin exactly once, even under repeated reconciliation cycles observing
    the same durable proof state.
    """

    fill, position = _make_fill_position("DRIFTUSDT", "long", 500)
    proof = _sealed_proof(fill, position, generated_utc="2026-07-28T05:00:00Z")
    manifest = _manifest_for([proof], [position])
    proof_source = _proof_source_from_store([proof], manifest)

    # The position drifted (e.g. re-sized) without a corresponding new
    # sealed proof -- a positive accounting mismatch, not mere absence.
    mutated_position = dict(position)
    mutated_position["net_quantity"] = 0.6

    ledger = _ledger_from_positions([mutated_position])
    reconciled_1, receipt_1 = paper_loop._paper_reconcile_ledger_to_accepted_fill_proofs(  # noqa: SLF001
        ledger, proof_source, generated_utc="2026-07-28T05:00:01Z"
    )
    assert receipt_1["phantom_position_count"] == 1
    assert receipt_1["used_margin_released_usd"] == pytest.approx(position["allocated_margin_usd"])
    assert len(paper_loop._paper_open_position_rows(reconciled_1)) == 0  # noqa: SLF001

    reconciled_2, receipt_2 = paper_loop._paper_reconcile_ledger_to_accepted_fill_proofs(  # noqa: SLF001
        reconciled_1, proof_source, generated_utc="2026-07-28T05:00:02Z"
    )
    assert receipt_2["phantom_position_count"] == 0
    assert receipt_2["used_margin_released_usd"] == 0.0

    total_released = (
        receipt_1["used_margin_released_usd"] + receipt_2["used_margin_released_usd"]
    )
    assert total_released == pytest.approx(position["allocated_margin_usd"])


# ---------------------------------------------------------------------------
# 5a. A valid partial close advances, rather than invalidates, position proof.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("side", ["long", "short"])
def test_coherent_reduce_only_partial_remainder_must_survive_restart_reconciliation(
    side: str,
) -> None:
    """A durable entry proof is not a permanent snapshot of open quantity.

    An admitted reduce-only close legitimately changes quantity, gross
    notional, allocated margin, and entry-cost remainder while leaving the
    position open.  Its hash-bound transition receipt must advance proof state;
    reconciliation must not reinterpret the coherent remainder as a phantom.
    The assertion is side-symmetric because both LONG and SHORT positions use
    the same accounting and restart contract.
    """

    close_side = "short" if side == "long" else "long"
    fill, position = _make_fill_position(
        f"PARTIAL{side.upper()}USDT",
        side,
        550,
        quantity=0.5,
        price=100.0,
        leverage=2.0,
    )
    proof = _sealed_proof(fill, position, generated_utc="2026-07-28T05:30:00Z")
    manifest = _manifest_for([proof], [position])
    proof_source = _proof_source_from_store([proof], manifest)

    close_material = {
        "schema_version": "paper_reduce_only_close_receipt_v1",
        "close_id": f"reduce-close-{side}-550",
        "position_id": position["position_id"],
        "position_generation_id": position["position_generation_id"],
        "entry_fill_id": fill["fill_id"],
        "source_fill_ids": [fill["fill_id"]],
        "position_side": side,
        "close_side": close_side,
        "quantity_before_close": 0.5,
        "close_quantity": 0.2,
        "remaining_quantity_after_close": 0.3,
        "reduce_only": True,
        "position_to_flat": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    close_receipt_sha256 = paper_loop._paper_canonical_sha256(close_material)  # noqa: SLF001
    close_receipt = {
        **close_material,
        "close_receipt_sha256": close_receipt_sha256,
    }

    remaining = dict(position)
    remaining.update(
        {
            "net_quantity": 0.3,
            "gross_notional_usd": 30.0,
            "allocated_margin_usd": 15.0,
            "entry_cost_is_final_close": False,
            "entry_fees_allocated_to_closes_usd": 0.01,
            "entry_fees_remaining_usd": 0.015,
        }
    )
    transition_material = {
        "schema_version": "paper_position_close_transition_proof_v1",
        "prior_open_position_fill_proof_id": proof["proof_id"],
        "prior_open_position_fill_proof_sha256": (
            paper_loop._paper_canonical_sha256(proof)  # noqa: SLF001
        ),
        "close_id": close_receipt["close_id"],
        "close_receipt_sha256": close_receipt_sha256,
        "position_id": remaining["position_id"],
        "position_generation_id": remaining["position_generation_id"],
        "position_side": side,
        "quantity_before_close": 0.5,
        "close_quantity": 0.2,
        "remaining_quantity": 0.3,
        "remaining_gross_notional_usd": 30.0,
        "remaining_allocated_margin_usd": 15.0,
        "remaining_position_payload_sha256": (
            paper_loop._paper_canonical_sha256(remaining)  # noqa: SLF001
        ),
        "quantity_conserved": True,
        "margin_released_by_reconciliation_usd": 0.0,
        "wallet_balance_mutation_usd": 0.0,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    transition_proof_id = paper_loop._paper_canonical_sha256(  # noqa: SLF001
        transition_material
    )
    transition_proof = {
        **transition_material,
        "transition_proof_id": transition_proof_id,
    }
    transition_proof_sha256 = paper_loop._paper_canonical_sha256(  # noqa: SLF001
        transition_proof
    )
    transition_proof["transition_proof_sha256"] = transition_proof_sha256

    # Simulates the next process lifetime: only durable ledger/proof records
    # remain.  No same-cycle admission state is available to rescue the row.
    ledger = _ledger_from_positions([remaining])
    ledger["closed_trades"] = [close_receipt]
    ledger["closes"] = [close_receipt]
    ledger["paper_position_close_transition_proofs"] = [transition_proof]

    reconciled, receipt = paper_loop._paper_reconcile_ledger_to_accepted_fill_proofs(  # noqa: SLF001
        ledger,
        proof_source,
        generated_utc="2026-07-28T05:31:00Z",
    )

    assert receipt["retained_position_count"] == 1
    assert receipt["phantom_position_count"] == 0
    assert receipt["used_margin_released_usd"] == 0.0
    assert receipt["wallet_balance_mutation_usd"] == 0.0
    assert receipt.get("wallet_mutation_allowed") is False
    assert len(paper_loop._paper_open_position_rows(reconciled)) == 1  # noqa: SLF001
    assert reconciled["closed_trades"] == [close_receipt]
    assert reconciled["closes"] == [close_receipt]
    assert receipt["proof_bindings"][0]["position_close_transition_proof_sha256"] == (
        transition_proof_sha256
    )


# ---------------------------------------------------------------------------
# 6. Wallet balance is never mutated by reconciliation.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scenario",
    ["uninitialized_with_positions", "valid_retain_all", "drift_removal"],
)
def test_no_wallet_balance_mutation_during_reconciliation(scenario: str) -> None:
    """Acceptance rule: reconciliation never mutates the paper wallet
    balance -- released margin only frees allocation headroom; it is not a
    wallet-balance write. Held across all three reconciliation branches:
    fail-closed-uninitialized, clean-pass-all-valid, and repaired-phantom.
    """

    if scenario == "uninitialized_with_positions":
        triples = _five_valid_triples("WAL")
        positions = [position for _, position, _ in triples]
        proof_source = paper_loop._paper_accepted_fill_proof_source(  # noqa: SLF001
            _FakeRedis({})
        )
        ledger = _ledger_from_positions(positions)
    elif scenario == "valid_retain_all":
        triples = _five_valid_triples("WAL2")
        positions = [position for _, position, _ in triples]
        proofs = [proof for _, _, proof in triples]
        manifest = _manifest_for(proofs, positions)
        proof_source = _proof_source_from_store(proofs, manifest)
        ledger = _ledger_from_positions(positions)
    else:
        fill, position = _make_fill_position("WALDRIFTUSDT", "short", 600)
        proof = _sealed_proof(fill, position, generated_utc="2026-07-28T06:00:00Z")
        manifest = _manifest_for([proof], [position])
        proof_source = _proof_source_from_store([proof], manifest)
        mutated = dict(position)
        mutated["net_quantity"] = 0.9
        ledger = _ledger_from_positions([mutated])

    _reconciled, receipt = paper_loop._paper_reconcile_ledger_to_accepted_fill_proofs(  # noqa: SLF001
        ledger, proof_source, generated_utc="2026-07-28T06:00:01Z"
    )

    assert receipt["wallet_balance_mutation_usd"] == 0.0
    assert receipt.get("wallet_mutation_allowed") is False


# ---------------------------------------------------------------------------
# 7. Reconciliation never emits a duplicate close.
# ---------------------------------------------------------------------------


def test_no_duplicate_close() -> None:
    """Acceptance rule: reconciliation never emits a second close for an
    already-closed/removed position -- the removed-position receipt is not a
    close event, and re-observing the same (now position-less) ledger a
    second time does not synthesize another one.
    """

    fill, position = _make_fill_position("CLOSEDRIFTUSDT", "long", 700)
    proof = _sealed_proof(fill, position, generated_utc="2026-07-28T07:00:00Z")
    manifest = _manifest_for([proof], [position])
    proof_source = _proof_source_from_store([proof], manifest)

    mutated_position = dict(position)
    mutated_position["net_quantity"] = 0.75

    ledger = _ledger_from_positions([mutated_position])
    ledger["closed_trades"] = []
    ledger["closes"] = []

    reconciled_1, receipt_1 = paper_loop._paper_reconcile_ledger_to_accepted_fill_proofs(  # noqa: SLF001
        ledger, proof_source, generated_utc="2026-07-28T07:00:01Z"
    )
    assert receipt_1["phantom_position_count"] == 1
    # The reconciliation receipt itself must not carry an economic close.
    assert reconciled_1.get("closed_trades", []) == []
    assert reconciled_1.get("closes", []) == []

    reconciled_2, receipt_2 = paper_loop._paper_reconcile_ledger_to_accepted_fill_proofs(  # noqa: SLF001
        reconciled_1, proof_source, generated_utc="2026-07-28T07:00:02Z"
    )
    assert receipt_2["phantom_position_count"] == 0
    assert reconciled_2.get("closed_trades", []) == []
    assert reconciled_2.get("closes", []) == []


# ---------------------------------------------------------------------------
# 8. Total margin is conserved across the reconciliation split.
# ---------------------------------------------------------------------------


def test_accounting_conservation() -> None:
    """Acceptance rule: sum(margin released) + sum(retained margin) equals
    the pre-reconciliation total allocated margin -- no capital appears or
    disappears without a receipt accounting for it.
    """

    triples = _five_valid_triples("ACC")
    valid_positions = [position for _, position, _ in triples]
    valid_proofs = [proof for _, _, proof in triples]

    drift_fill, drift_position = _make_fill_position("ACCDRIFTUSDT", "short", 800)
    drift_proof = _sealed_proof(drift_fill, drift_position, generated_utc="2026-07-28T08:00:00Z")
    mutated_drift_position = dict(drift_position)
    mutated_drift_position["net_quantity"] = 1.5  # positive accounting mismatch

    all_positions = valid_positions + [mutated_drift_position]
    all_proofs = valid_proofs + [drift_proof]
    manifest = _manifest_for(all_proofs, valid_positions + [drift_position])
    proof_source = _proof_source_from_store(all_proofs, manifest)

    pre_total_margin = sum(
        float(row["allocated_margin_usd"]) for row in valid_positions + [drift_position]
    )

    ledger = _ledger_from_positions(all_positions)
    reconciled, receipt = paper_loop._paper_reconcile_ledger_to_accepted_fill_proofs(  # noqa: SLF001
        ledger, proof_source, generated_utc="2026-07-28T08:00:01Z"
    )

    retained_total_margin = sum(
        float(row.get("allocated_margin_usd") or 0.0)
        for row in paper_loop._paper_open_position_rows(reconciled)  # noqa: SLF001
    )
    released_margin = float(receipt["used_margin_released_usd"])

    assert retained_total_margin + released_margin == pytest.approx(pre_total_margin)
    assert receipt["wallet_balance_mutation_usd"] == 0.0


# ---------------------------------------------------------------------------
# 9. Retain/remove rules are side-symmetric.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("side", ["long", "short"])
def test_long_and_short_symmetry(side: str) -> None:
    """Acceptance rule: the retain-valid / remove-phantom rules apply
    identically regardless of position side. A valid position is retained
    and a genuinely-invalid position (of the same side) is removed with
    identical mechanics for both long and short.
    """

    valid_fill, valid_position = _make_fill_position(f"SYM{side.upper()}USDT", side, 900)
    valid_proof = _sealed_proof(valid_fill, valid_position, generated_utc="2026-07-28T09:00:00Z")

    invalid_fill, invalid_position = _make_fill_position(
        f"BAD{side.upper()}USDT", side, 901
    )
    invalid_proof = _sealed_proof(
        invalid_fill, invalid_position, generated_utc="2026-07-28T09:00:00Z"
    )
    mutated_invalid_position = dict(invalid_position)
    mutated_invalid_position["net_quantity"] = (
        invalid_position["net_quantity"] + 0.1
    )  # drift -> positive accounting mismatch regardless of side

    manifest = _manifest_for(
        [valid_proof, invalid_proof], [valid_position, invalid_position]
    )
    proof_source = _proof_source_from_store([valid_proof, invalid_proof], manifest)

    ledger = _ledger_from_positions([valid_position, mutated_invalid_position])
    reconciled, receipt = paper_loop._paper_reconcile_ledger_to_accepted_fill_proofs(  # noqa: SLF001
        ledger, proof_source, generated_utc="2026-07-28T09:00:01Z"
    )

    retained_symbols = {
        row["symbol"] for row in paper_loop._paper_open_position_rows(reconciled)  # noqa: SLF001
    }
    assert retained_symbols == {valid_position["symbol"]}
    assert receipt["phantom_position_count"] == 1
    assert receipt["used_margin_released_usd"] == pytest.approx(
        invalid_position["allocated_margin_usd"]
    )
    assert receipt["wallet_balance_mutation_usd"] == 0.0


# ---------------------------------------------------------------------------
# 10. Restart reconstruction retains every proof-backed position.
# ---------------------------------------------------------------------------


def test_restart_reconstruction_retains_all_proof_backed_positions() -> None:
    """Acceptance rule: after a simulated process restart -- the ledger is
    freshly (re)loaded with no in-cycle state, but the durable proof rail
    (proofs + completed manifest) persisted BEFORE the restart -- every
    proof-backed position is retained. None is dropped merely because
    there is no fresh same-cycle admission ("the new rail") when a valid
    durable proof from before the restart already exists.
    """

    triples = _five_valid_triples("RESTART")
    positions = [position for _, position, _ in triples]
    proofs = [proof for _, _, proof in triples]

    # Manifest/proofs represent state durably written in a PRIOR process
    # lifetime -- generated_utc predates "now" to make the restart explicit.
    manifest = _manifest_for(proofs, positions, generated_utc="2026-07-27T23:00:00Z")
    proof_source = _proof_source_from_store(proofs, manifest)

    # Freshly (re)loaded ledger after restart -- a plain dict with no
    # in-memory reconciliation markers from the prior process.
    fresh_ledger_after_restart = {
        "open_positions": [dict(p) for p in positions],
        "positions_by_symbol": {p["symbol"]: dict(p) for p in positions},
        "open_position_count": len(positions),
    }

    reconciled, receipt = paper_loop._paper_reconcile_ledger_to_accepted_fill_proofs(  # noqa: SLF001
        fresh_ledger_after_restart,
        proof_source,
        generated_utc="2026-07-28T00:00:00Z",
    )

    assert receipt["status"] == "PASS"
    assert receipt["retained_position_count"] == 5
    assert receipt["phantom_position_count"] == 0
    assert len(paper_loop._paper_open_position_rows(reconciled)) == 5  # noqa: SLF001
    retained_symbols = {
        row["symbol"] for row in paper_loop._paper_open_position_rows(reconciled)  # noqa: SLF001
    }
    assert retained_symbols == {p["symbol"] for p in positions}


# ---------------------------------------------------------------------------
# Plus: the crux distinction -- INITIALIZED-empty vs UNINITIALIZED-absent.
# ---------------------------------------------------------------------------


def test_empty_INITIALIZED_vs_UNINITIALIZED_distinction() -> None:
    """Acceptance rule (the crux of operator requirement #1): an explicitly
    initialized-but-genuinely-empty proof set (sealed by a completed
    manifest, 0 positions to reconcile) IS authoritative -- retaining
    nothing is correct because there is nothing to retain. An
    uninitialized/absent proof store observed WITH open positions present is
    NOT authoritative for "zero legitimate positions" -- it must retain all
    of them and fail closed instead of wiping.
    """

    # Part A: explicitly initialized + genuinely empty (0 proofs, 0
    # positions) -- authoritative; retaining nothing is the correct outcome.
    empty_manifest = paper_loop._paper_open_position_fill_proof_manifest(  # noqa: SLF001
        [], [], generated_utc="2026-07-28T10:00:00Z"
    )
    assert empty_manifest["initialization_state"] == "EMPTY_INITIALIZED_PROOF_SET"
    empty_source = _proof_source_from_store([], empty_manifest)
    empty_reconciled, empty_receipt = (
        paper_loop._paper_reconcile_ledger_to_accepted_fill_proofs(  # noqa: SLF001
            {"open_positions": []}, empty_source, generated_utc="2026-07-28T10:00:01Z"
        )
    )
    assert empty_receipt["status"] == "PASS"
    assert empty_receipt["retained_position_count"] == 0
    assert empty_receipt["phantom_position_count"] == 0
    assert len(paper_loop._paper_open_position_rows(empty_reconciled)) == 0  # noqa: SLF001

    # Part B: uninitialized/absent store (key never written) WITH 5 real
    # positions present -- NOT authoritative; must retain all, fail closed.
    triples = _five_valid_triples("CRUX")
    positions = [position for _, position, _ in triples]
    absent_source = paper_loop._paper_accepted_fill_proof_source(  # noqa: SLF001
        _FakeRedis({})
    )
    absent_ledger = _ledger_from_positions(positions)
    absent_reconciled, absent_receipt = (
        paper_loop._paper_reconcile_ledger_to_accepted_fill_proofs(  # noqa: SLF001
            absent_ledger, absent_source, generated_utc="2026-07-28T10:00:02Z"
        )
    )

    assert absent_receipt["status"] != "PASS"
    assert absent_receipt["retained_position_count"] == 5
    assert absent_receipt["phantom_position_count"] == 0
    assert absent_receipt["used_margin_released_usd"] == 0.0
    assert len(paper_loop._paper_open_position_rows(absent_reconciled)) == 5  # noqa: SLF001

    # The two states must be observably distinguishable from one another --
    # an absent store and an initialized-empty store must not collapse to
    # the same classification (this IS the CG-F063 defect if they do).
    assert (
        empty_source.get("initialization_state")
        != absent_source.get("initialization_state")
    ) or (empty_source.get("status") != absent_source.get("status"))
