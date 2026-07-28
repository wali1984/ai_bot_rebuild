"""Point-in-time allocation contract must accept a reconstructed paper ledger.

Root defect (block "A"): when the paper loop rebuilds ``existing_ledger`` from
``v2:paper:positions`` (an open position exists), the reconstructed payload
carries ``open_positions`` (so ``paper_ledger_open_position_count`` > 0) but no
ledger-level ``generated_at``/``generated_utc``/``updated_at``.  The allocation
point-in-time contract then requires ``paper_ledger_generated_at`` and rejects
with ``ALLOCATION_INPUT_TIME_MISSING:paper_ledger_generated_at`` even though the
open-position rows carry a real, authenticated producer timestamp
(``position_reconstruction_generated_at``).

That spurious block fires for EVERY new candidate (long or short) whenever any
position is open, and cascades: allocation PIT BLOCKED -> ``risk_veto`` ->
adaptive allocator returns zero size.

These tests assert the desired (fixed) behaviour: the reconstructed generation
timestamp is derived from the authenticated open-position reconstruction clock,
the allocation PIT passes for a valid directional SHORT, and the fail-closed
rails remain intact (missing timestamp still blocks; a genuinely non-flat
position still blocks a new ordinary entry).
"""

from __future__ import annotations

from datetime import UTC, datetime

from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop


def _reconstructed_open_position(
    *,
    symbol: str = "AAVEUSDT",
    side: str = "short",
    reconstruction_time: str = "2026-07-28T00:08:44.750589Z",
) -> dict[str, object]:
    """Compact open-position row exactly as ``v2:paper:positions`` publishes it.

    It carries ``position_reconstruction_generated_at`` but NO ledger-level
    ``generated_at``/``generated_utc``/``updated_at`` (matching the live key).
    """

    return {
        "symbol": symbol,
        "side": side,
        "position_state": "OPEN_POSITION",
        "net_quantity": 0.8 if side == "short" else 0.8,
        "position_reconstruction_generated_at": reconstruction_time,
        "position_reconstruction_schema_version": "PAPER_OPEN_POSITION_RECONSTRUCTION_V3",
        "generated_at": None,
        "generated_utc": None,
        "updated_at": None,
    }


def _reconstructed_ledger(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "open_positions": rows,
        "positions_by_symbol": {str(r["symbol"]).upper(): r for r in rows},
        "open_position_count": len(rows),
        "lifecycle_state_source": (
            "v2:paper:positions+v2:paper:closed_trades+v2:paper:outcome_labels"
        ),
        # Deliberately no ledger-level generated_at / generated_utc / updated_at.
    }


def _allocation_intent(generated_at: object) -> dict[str, object]:
    """Build the ledger-time slice of an allocation intent as the loop does."""

    now = paper_loop._utc_iso()
    return {
        "paper_ledger_generated_at": generated_at,
        "paper_ledger_observed_at": now,
        "paper_ledger_open_position_count": 1,
        "open_exposure_observed_at": now,
        "portfolio_context_observed_at": now,
        "paper_exchange_filter_status": "READY",
        "paper_exchange_filter_available_at": now,
        "paper_exchange_filter_observed_at": now,
    }


def _derive_paper_ledger_generated_at(existing_ledger: dict[str, object]) -> object:
    """Reproduce the loop's line-44913 assignment (post-fix chain)."""

    return paper_loop._first_present(
        existing_ledger.get("generated_at"),
        existing_ledger.get("generated_utc"),
        existing_ledger.get("updated_at"),
        paper_loop._paper_ledger_open_position_generation_timestamp(existing_ledger),
    )


# --------------------------------------------------------------------------- #
# Defect A: reconstructed ledger with an open position must yield a generated_at
# --------------------------------------------------------------------------- #
def test_reconstructed_ledger_generated_at_derived_from_position_clock() -> None:
    ledger = _reconstructed_ledger([_reconstructed_open_position(side="short")])

    generated_at = _derive_paper_ledger_generated_at(ledger)

    assert generated_at == "2026-07-28T00:08:44.750589Z"
    assert paper_loop._strict_aware_utc_time(generated_at) is not None


def test_allocation_pit_passes_for_short_with_reconstructed_ledger() -> None:
    ledger = _reconstructed_ledger([_reconstructed_open_position(side="short")])
    generated_at = _derive_paper_ledger_generated_at(ledger)

    intent = _allocation_intent(generated_at)
    result = paper_loop._paper_allocation_point_in_time_contract(
        intent,
        allocation_decision_time=datetime.now(UTC),
        include_dynamic_envelope=False,
    )

    assert result["status"] == "PASS", result["rejection_reasons"]
    assert not any(
        reason.startswith("ALLOCATION_INPUT_TIME_MISSING:paper_ledger_generated_at")
        for reason in result["rejection_reasons"]
    )


def test_allocation_pit_blocked_without_fix_derivation() -> None:
    """Guard: with NO derivation (old behaviour) the PIT still blocks.

    This proves the block is genuinely produced by the missing timestamp, so the
    fix is populating a real value rather than loosening the contract.
    """

    intent = _allocation_intent(generated_at=None)
    result = paper_loop._paper_allocation_point_in_time_contract(
        intent,
        allocation_decision_time=datetime.now(UTC),
        include_dynamic_envelope=False,
    )

    assert result["status"] == "BLOCKED"
    assert "ALLOCATION_INPUT_TIME_MISSING:paper_ledger_generated_at" in (
        result["rejection_reasons"]
    )


# --------------------------------------------------------------------------- #
# Long/short symmetry
# --------------------------------------------------------------------------- #
def test_generated_at_derivation_is_side_symmetric() -> None:
    long_ledger = _reconstructed_ledger(
        [_reconstructed_open_position(symbol="ETHUSDT", side="long")]
    )
    short_ledger = _reconstructed_ledger(
        [_reconstructed_open_position(symbol="ETHUSDT", side="short")]
    )

    assert _derive_paper_ledger_generated_at(long_ledger) == _derive_paper_ledger_generated_at(
        short_ledger
    )


def test_generated_at_uses_latest_reconstruction_clock() -> None:
    ledger = _reconstructed_ledger(
        [
            _reconstructed_open_position(
                symbol="AAVEUSDT",
                side="short",
                reconstruction_time="2026-07-28T00:01:00.000000Z",
            ),
            _reconstructed_open_position(
                symbol="ETHUSDT",
                side="long",
                reconstruction_time="2026-07-28T00:09:00.000000Z",
            ),
        ]
    )

    assert _derive_paper_ledger_generated_at(ledger) == "2026-07-28T00:09:00.000000Z"


# --------------------------------------------------------------------------- #
# True negatives: fail-closed rails must remain intact
# --------------------------------------------------------------------------- #
def test_generated_at_none_when_no_authenticated_reconstruction_clock() -> None:
    """A row with NO reconstruction/producer clock must NOT be back-filled."""

    row = _reconstructed_open_position(side="short")
    row["position_reconstruction_generated_at"] = None
    ledger = _reconstructed_ledger([row])

    assert paper_loop._paper_ledger_open_position_generation_timestamp(ledger) is None
    assert _derive_paper_ledger_generated_at(ledger) is None


def test_naive_reconstruction_clock_is_rejected() -> None:
    """A timezone-naive clock is not a valid PIT source (fail closed)."""

    row = _reconstructed_open_position(side="short")
    row["position_reconstruction_generated_at"] = "2026-07-28T00:08:44"  # no tz
    ledger = _reconstructed_ledger([row])

    assert paper_loop._paper_ledger_open_position_generation_timestamp(ledger) is None


def test_real_open_position_reports_non_flat_state() -> None:
    """Defect C is LEGITIMATE: the per-symbol source that feeds the router's
    ``ORDINARY_ROUTER_POSITION_NOT_FLAT_FOR_NEW_ENTRY`` rail correctly reports a
    genuinely open symbol as non-flat (the rail must remain)."""

    short_state = paper_loop._derive_position_state(
        _reconstructed_ledger([_reconstructed_open_position(side="short")]),
        "AAVEUSDT",
    )
    assert short_state == "SHORT"
    assert short_state != "FLAT"  # -> router appends the not-flat hard reason.


def test_flat_symbol_reports_flat_state_symmetric() -> None:
    """Symmetry: a symbol with no open inventory is FLAT for a new long OR short."""

    ledger = _reconstructed_ledger(
        [_reconstructed_open_position(symbol="AAVEUSDT", side="short")]
    )
    # A different, flat symbol is not blocked by the not-flat rail.
    assert paper_loop._derive_position_state(ledger, "CAKEUSDT") == "FLAT"
    # And a long open position is symmetrically reported as non-flat.
    long_ledger = _reconstructed_ledger(
        [_reconstructed_open_position(symbol="AAVEUSDT", side="long")]
    )
    assert paper_loop._derive_position_state(long_ledger, "AAVEUSDT") == "LONG"
