from __future__ import annotations

from copy import deepcopy

from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop
from v2.backend.app.services.paper_trade_management import lifecycle
from v2.backend.app.services.paper_trade_management.generation_identity import (
    POSITION_ID_VERSION,
)
from v2.backend.app.services.paper_trade_management.position_state import (
    PAPER_POSITION_RECONSTRUCTION_PERSISTENCE_FIELDS,
    PaperNetPosition,
    paper_position_reconstruction_hash,
    validate_paper_position_reconstruction,
)


def _partially_closed_position_payload() -> dict[str, object]:
    position = PaperNetPosition(
        position_id="paper_pos_btc_generation_1",
        legacy_position_id="paper_pos_btc",
        position_generation_id="generation-1",
        position_id_version=POSITION_ID_VERSION,
        entry_generation_time_utc="2026-07-17T10:00:00Z",
        symbol="BTCUSDT",
        side="long",
        net_quantity=6.0,
        avg_entry_price=160.0,
        opened_est="2026-07-17T10:00:00Z",
        fill_ids=["fill-entry-1", "fill-entry-2"],
        realized_pnl=17.5,
        effective_leverage=2.0,
        recommended_leverage=2.0,
        margin_mode_simulated="isolated_paper_simulated",
        entry_fees_incurred_usd=1.6,
        entry_fees_remaining_usd=0.96,
        entry_fees_allocated_to_closes_usd=0.64,
        entry_slippage_incurred_usd=0.8,
        entry_slippage_remaining_usd=0.48,
        entry_slippage_allocated_to_closes_usd=0.32,
        entry_fee_cost_sources=["EXACT_FILL_FEE"],
        entry_slippage_cost_sources=["EXACT_FILL_SLIPPAGE"],
        entry_cost_basis_status="COMPLETE_ENTRY_FEE_AND_SLIPPAGE_USD_BASIS",
    )
    return position.to_payload(generated_utc="2026-07-17T11:00:00Z")


def test_accepted_state_compaction_preserves_partial_position_reconstruction() -> None:
    snapshot = _partially_closed_position_payload()
    assert validate_paper_position_reconstruction(snapshot) == []

    compact = paper_loop._compact_accepted_fill_for_state(snapshot)  # noqa: SLF001

    for field_name in PAPER_POSITION_RECONSTRUCTION_PERSISTENCE_FIELDS:
        if field_name in snapshot and snapshot[field_name] is not None:
            assert compact[field_name] == snapshot[field_name]
    assert validate_paper_position_reconstruction(compact) == []

    replayed = paper_loop._accepted_fill_from_open_position(compact)  # noqa: SLF001
    assert validate_paper_position_reconstruction(replayed) == []
    assert replayed["net_quantity"] == 6.0
    assert replayed["quantity"] == 6.0
    assert replayed["source_fill_ids"] == ["fill-entry-1", "fill-entry-2"]


def test_restart_reconstruction_hash_binds_leverage_and_allocated_margin() -> None:
    snapshot = _partially_closed_position_payload()

    leverage_tampered = deepcopy(snapshot)
    leverage_tampered["effective_leverage"] = 75.0
    assert "POSITION_RECONSTRUCTION_HASH_MISMATCH" in (
        validate_paper_position_reconstruction(leverage_tampered)
    )

    rehashed_with_inconsistent_margin = deepcopy(leverage_tampered)
    rehashed_with_inconsistent_margin["position_reconstruction_hash"] = (
        paper_position_reconstruction_hash(rehashed_with_inconsistent_margin)
    )
    assert "POSITION_RECONSTRUCTION_MARGIN_LEVERAGE_IDENTITY_INVALID" in (
        validate_paper_position_reconstruction(rehashed_with_inconsistent_margin)
    )


def test_accepted_state_compaction_preserves_netting_receipt_hash_material() -> None:
    receipt = lifecycle._attach_netting_receipt(  # noqa: SLF001
        {
            "fill_id": "fill-reducing-1",
            "ledger_row_id": "fill-reducing-1",
            "symbol": "BTCUSDT",
            "side": "short",
            "paper_only": True,
            "places_real_order": False,
        },
        close_event={
            "close_id": "close-1",
            "position_generation_id": "generation-1",
        },
        input_quantity=6.0,
        consumed_quantity=4.0,
        residual_quantity=2.0,
    )

    compact = paper_loop._compact_accepted_fill_for_state(receipt)  # noqa: SLF001

    for field_name in paper_loop.PAPER_NETTING_FILL_RECEIPT_PERSISTENCE_FIELDS:
        assert compact[field_name] == receipt[field_name]
    assert lifecycle._netting_receipt_hash(compact) == receipt[  # noqa: SLF001
        "paper_netting_fill_receipt_hash"
    ]
