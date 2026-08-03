from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from v2.backend.app.services.replay_backtest_runner.service import (
    assemble_replay_backtest_step,
    assemble_replay_backtest_summary,
)


BACKTESTING_STATUS_SCHEMA_VERSION = "v2_backtesting_compat_status_v1"


def build_backtesting_runtime_status(
    *,
    latest_replay_summary: Mapping[str, Any] | None = None,
    latest_backtest_request: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    summary = dict(latest_replay_summary or {})
    request = dict(latest_backtest_request or {})
    requested_live_mode = request.get("live_mode") is True or request.get("places_real_order") is True
    blockers: list[str] = []
    if requested_live_mode:
        blockers.append("live_backtest_order_mutation_not_allowed")

    return {
        "schema_version": BACKTESTING_STATUS_SCHEMA_VERSION,
        "classification": "V2_BACKTESTING_RUNTIME_READY"
        if not blockers
        else "V2_BACKTESTING_RUNTIME_BLOCKED",
        "source": "v2.backend.app.services.backtesting",
        "backing_runtime": "v2.backend.app.services.replay_backtest_runner",
        "capabilities": {
            "assemble_replay_backtest_step": callable(assemble_replay_backtest_step),
            "assemble_replay_backtest_summary": callable(assemble_replay_backtest_summary),
            "paper_ledger_projection": True,
            "historical_aggregate_index": True,
        },
        "latest_replay_summary": {
            "replay_run_id": summary.get("replay_run_id"),
            "total_steps_count": summary.get("total_steps_count"),
            "record_allow_steps_count": summary.get("record_allow_steps_count"),
            "record_deny_steps_count": summary.get("record_deny_steps_count"),
            "live_blocked": summary.get("live_blocked", True),
        },
        "blockers": blockers,
        "live_safety": {
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "trader_execution_enabled": False,
            "places_real_order": False,
            "exchange_action_taken": False,
            "writes_exchange_orders": False,
            "writes_legacy_redis": False,
        },
    }
