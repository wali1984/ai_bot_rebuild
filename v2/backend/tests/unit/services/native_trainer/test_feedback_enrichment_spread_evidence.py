from __future__ import annotations

from v2.backend.app.services.native_trainer.feedback_enrichment import (
    audit_quality_rejection_reasons,
)


def _clean_audit_quality_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "actual_observed_spread_entry_bps": 1.4,
        "entry_spread_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
        "actual_observed_spread_exit_bps": 1.6,
        "exit_spread_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
        "expected_slippage_bps": 0.8,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_EXIT_SPREAD",
        "implementation_shortfall_usd": 0.0,
        "squeeze_evidence_score": 0.0,
        "squeeze_evidence_source": "DERIVED_FROM_LIQUIDATION_OI_FUNDING_ORDERBOOK_CONTEXT",
        "mfe_bps": 20.0,
        "mae_bps": 10.0,
        "intra_trade_high_price": 101.0,
        "intra_trade_low_price": 99.0,
        "exit_reason": "TIER_2_TAKE_PROFIT",
        "trailing_stop_history": [],
        "microstructure_context": {
            "bid_ask_spread_bps": 2.0,
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
        },
    }
    row.update(overrides)
    return row


def test_observed_exit_spread_source_overrides_static_entry_source() -> None:
    row = _clean_audit_quality_row(
        actual_observed_spread_entry_bps=2.0,
        entry_spread_source="V2_STRATEGY_ROUTER_ALLOCATOR_CONTEXT",
        actual_observed_spread_exit_bps=1.2135186,
        exit_spread_source="V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:ARBUSDT",
        microstructure_context={
            "bid_ask_spread_bps": 2.0,
            "source": "V2_STRATEGY_ROUTER_ALLOCATOR_CONTEXT",
        },
    )

    assert "UNSOURCED_OBSERVED_SPREAD_EVIDENCE" not in audit_quality_rejection_reasons(row)


def test_static_only_spread_source_stays_quarantined() -> None:
    row = _clean_audit_quality_row(
        actual_observed_spread_entry_bps=2.0,
        entry_spread_source="V2_STRATEGY_ROUTER_ALLOCATOR_CONTEXT",
        actual_observed_spread_exit_bps=None,
        exit_spread_source=None,
        microstructure_context={
            "bid_ask_spread_bps": 2.0,
            "source": "V2_STRATEGY_ROUTER_ALLOCATOR_CONTEXT",
        },
    )

    assert "UNSOURCED_OBSERVED_SPREAD_EVIDENCE" in audit_quality_rejection_reasons(row)
