#!/usr/bin/env python3
"""Bounded, isolated S13 canary over the production paper lifecycle mechanism.

No Redis keys or live/exchange paths are touched.  The synthetic row is tagged
as an engineering transport canary and is never eligible economic evidence.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v2.backend.app.services.paper_trade_management.caps import PaperExposureCaps
from v2.backend.app.services.paper_trade_management.exits import PaperExitConfig
from v2.backend.app.services.paper_trade_management.lifecycle import (
    PaperLifecycleConfig,
    reconcile_paper_lifecycle,
)

RESULT_PATH = ROOT / "goal_state/PERMANENT_SYSTEM_RECOVERY/s13_max_hold_transport_canary_result.json"


def _fill() -> dict:
    return {
        "fill_id": "s13_transport_canary_fill",
        "ledger_row_id": "s13_transport_canary_fill",
        "intent_id": "s13_transport_canary_intent",
        "symbol": "BTCUSDT",
        "side": "long",
        "quantity": 1.0,
        "notional": 100.0,
        "notional_usdt": 100.0,
        "entry_price": 100.0,
        "fill_price": 100.0,
        "fill_price_utc": "2026-07-26T18:00:00Z",
        "generated_utc": "2026-07-26T18:00:00Z",
        "signal_id": "s13_transport_canary_signal",
        "prediction_id": "s13_transport_canary_prediction",
        "risk_decision_id": "s13_transport_canary_risk",
        "orchestrator_decision_id": "s13_transport_canary_orchestrator",
        "decision_id": "s13_transport_canary_orchestrator",
        "market_state_id": "s13_transport_canary_market",
        "feature_snapshot_id": "s13_transport_canary_feature",
        "mtf_snapshot_id": "s13_transport_canary_mtf",
        "feature_cutoff": "2026-07-26T17:59:00Z",
        "decision_time": "2026-07-26T18:00:00Z",
        "available_at": "2026-07-26T17:59:30Z",
        "selected_action": "long",
        "model_version": "s13_transport_canary",
        "checkpoint_id": "s13_transport_canary",
        "source_hashes": {"feature_vector_hash": "s13_transport_canary"},
        "trainer_source": "ENGINEERING_TRANSPORT_CANARY",
        "timeframe": "1m",
        "paper_fill_allowed": True,
        "engineering_canary": True,
        "transport_canary": True,
        "counts_as_economic_evidence": False,
    }


def main() -> int:
    result = reconcile_paper_lifecycle(
        existing_ledger={},
        accepted_fills=[_fill()],
        mark_prices={"BTCUSDT": 100.0},
        generated_utc="2026-07-26T18:00:11Z",
        config=PaperLifecycleConfig(
            portfolio_equity_usdt=10_000.0,
            exposure_caps=PaperExposureCaps(max_single_symbol_exposure_pct=0.05),
            exit_config=PaperExitConfig(
                max_hold_seconds=10,
                take_profit_bps=99_999.0,
                stop_loss_bps=99_999.0,
            ),
        ),
    )
    closes = result.get("closed_trades") or []
    close = closes[0] if len(closes) == 1 else {}
    expected_net = (
        float(close.get("gross_realized_pnl_usd") or 0.0)
        - float(close.get("total_fees_usd") or 0.0)
        - float(close.get("total_slippage_usd") or 0.0)
        + float(close.get("funding_pnl_usd") or 0.0)
    )
    checks = {
        "one_fill_accepted": len(result.get("accepted_open_fills") or []) == 1,
        "max_hold_exit": close.get("close_reason") == "TIER_4_MAX_HOLD_TIME",
        "reduce_only_close": close.get("reduce_only") is True,
        "long_to_flat": close.get("position_transition") == "LONG_TO_FLAT",
        "quantity_fully_consumed": close.get("remaining_quantity_after_close") == 0.0,
        "margin_release_required": close.get("margin_release_required") is True,
        "no_open_position": not (result.get("open_positions") or []),
        "zero_open_notional": float(result.get("total_open_notional") or 0.0) == 0.0,
        "accounting_reconciled": math.isclose(
            float(close.get("realized_net_pnl_usd") or 0.0),
            expected_net,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ),
        "exchange_action_taken": False,
    }
    payload = {
        "schema_version": "s13_max_hold_transport_canary_v1",
        "run_utc": datetime.now(UTC).isoformat(),
        "production_binding": "paper_trade_management.lifecycle.reconcile_paper_lifecycle",
        "test_max_hold_seconds": 10,
        "counts_as_economic_evidence": False,
        "checks": checks,
        "close_receipt": {
            key: close.get(key)
            for key in (
                "close_id", "close_reason", "reduce_only", "close_position",
                "position_transition", "closed_quantity", "remaining_quantity_after_close",
                "margin_release_required", "realized_net_pnl_usd",
            )
        },
        "all_pass": all(
            value for name, value in checks.items() if name != "exchange_action_taken"
        ) and checks["exchange_action_taken"] is False,
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return 0 if payload["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
