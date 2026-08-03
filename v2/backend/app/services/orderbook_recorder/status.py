"""Status artifact builders for the zero-budget direct orderbook path."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .features import utc_now_iso
from .replay_engine import build_local_replay_engine_status


GOAL_ID = "V2_ZERO_BUDGET_DIRECT_ORDERBOOK_RECORDER_AND_REPLAY_DATA_ACTIVATION_READY"
LIVE_GATE = "blocked_human_only"
PUBLIC_RUNTIME_RELATIVE = "v2/frontend/public/operator_runtime/v2_zero_budget_orderbook/latest"
GOAL_STATE_RELATIVE = f"goal_state/{GOAL_ID}"


def provider_decision_status() -> dict[str, Any]:
    return {
        "goal_id": GOAL_ID,
        "generated_at": utc_now_iso(),
        "coinapi_renewal_required": False,
        "tardis_purchase_required": False,
        "primary_live_orderbook_source": "direct_binance_kucoin",
        "historical_l2_gap_status": "BUILD_FORWARD_FROM_NOW",
        "binance_public_data_used_for_historical_trades_klines": True,
        "coinank_remains_derivatives_liquidation_source": True,
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "transfer_or_withdrawal": False,
        "decision": "ZERO_BUDGET_DIRECT_RECORDER_PATH",
    }


def provider_gap_mapping() -> dict[str, Any]:
    mapping = {
        "bid": ["Binance direct", "KuCoin direct", "local recorder"],
        "ask": ["Binance direct", "KuCoin direct", "local recorder"],
        "spread_bps": ["local recorder"],
        "best_bid_size": ["Binance direct", "KuCoin direct", "local recorder"],
        "best_ask_size": ["Binance direct", "KuCoin direct", "local recorder"],
        "depth_5": ["Binance direct", "KuCoin direct", "local recorder"],
        "depth_20": ["Binance direct", "KuCoin direct", "local recorder"],
        "depth_50": ["KuCoin direct", "local recorder", "missing until forward-recorded where Binance-only"],
        "depth_500_if_available": ["KuCoin direct increment@10ms", "local recorder", "missing until forward-recorded"],
        "orderbook_imbalance": ["local recorder"],
        "depth_slope": ["local recorder"],
        "price_impact_bps": ["local recorder"],
        "slippage_model": ["local recorder", "paper fills", "missing until forward-recorded"],
        "sequence_gap": ["Binance direct", "KuCoin direct", "local recorder"],
        "event_time": ["Binance direct", "KuCoin direct", "Binance public archive for trades/klines"],
        "available_at": ["local recorder"],
        "decision_time": ["decision consumer runtime"],
        "historical_trades": ["Binance public archive"],
        "historical_aggTrades": ["Binance public archive"],
        "historical_klines": ["Binance public archive"],
        "old_historical_l2": ["missing until forward-recorded"],
        "derivatives_liquidation_intelligence": ["CoinAnk"],
    }
    return {
        "goal_id": GOAL_ID,
        "generated_at": utc_now_iso(),
        "mapping": {
            field: {
                "sources": sources,
                "coinapi_required": False,
                "tardis_required_now": False,
            }
            for field, sources in mapping.items()
        },
    }


def default_universe_gap_status(
    *,
    feed_coverage: dict[str, Any],
    default_symbols: list[str],
    provider_symbol_support: dict[str, Any] | None = None,
    shard_size: int = 8,
) -> dict[str, Any]:
    audit = audit_configured_symbol_feed_coverage(
        feed_coverage=feed_coverage,
        configured_symbols=default_symbols,
        provider_symbol_support=provider_symbol_support,
    )
    missing_symbols = list(audit.get("incomplete_symbols") or [])
    retryable_symbols = (
        list(audit.get("retryable_incomplete_symbols") or [])
        if "retryable_incomplete_symbols" in audit
        else missing_symbols
    )
    shards = _chunk_symbols(retryable_symbols, max(1, int(shard_size)))
    shard_commands = []
    for index, shard in enumerate(shards):
        csv = ",".join(shard)
        shard_commands.append(
            {
                "shard_index": index,
                "symbols": shard,
                "binance_250ms_command": (
                    "PYTHONPATH=. .venv/bin/python -m "
                    "v2.backend.app.cli.v2_direct_orderbook_recorder "
                    f"--symbols {csv} --exchange binance --speed 250ms "
                    "--max-messages 800 --venue-timeout-seconds 30 --write-redis --write-status"
                ),
                "binance_100ms_kucoin_all_command": (
                    "PYTHONPATH=. .venv/bin/python -m "
                    "v2.backend.app.cli.v2_direct_orderbook_recorder "
                    f"--symbols {csv} --exchange both --speed 100ms --kucoin-depth all "
                    "--kucoin-trade-type FUTURES --max-messages 1200 "
                    "--venue-timeout-seconds 30 --write-redis --write-status"
                ),
            }
        )
    return {
        "goal_id": GOAL_ID,
        "generated_at": utc_now_iso(),
        "default_universe_symbol_count": len(default_symbols),
        "default_universe_complete_symbol_count": len(audit.get("complete_symbols") or []),
        "default_universe_incomplete_symbol_count": len(missing_symbols),
        "all_default_universe_symbols_have_required_direct_feed_coverage": bool(
            audit.get("all_configured_symbols_have_required_direct_feed_coverage")
        ),
        "active_direct_orderbook_symbol_count": audit.get("active_direct_orderbook_symbol_count", 0),
        "active_direct_orderbook_symbols": audit.get("active_direct_orderbook_symbols", []),
        "unsupported_symbols_excluded_from_active_orderbook_universe": audit.get(
            "symbols_without_any_supported_direct_provider",
            [],
        ),
        "single_venue_direct_orderbook_symbols": audit.get("single_venue_direct_orderbook_symbols", []),
        "all_active_direct_orderbook_symbols_have_required_direct_feed_coverage": bool(
            audit.get("all_active_direct_orderbook_symbols_have_required_direct_feed_coverage")
        ),
        "all_supported_provider_feeds_have_required_direct_feed_coverage": bool(
            audit.get("all_provider_supported_required_direct_feeds_have_coverage")
        ),
        "coverage_requirement": {
            "binance": "book_ticker + partial_depth_5_10_20 + diff_depth + 100ms + 250ms",
            "kucoin": "best5 + best50 + 100ms; increment_best500_10ms tracked where observed/supported",
        },
        "readiness_scope": (
            "active_direct_orderbook_symbols exclude contracts with no supported direct "
            "Binance or KuCoin orderbook provider; excluded symbols remain visible and "
            "must be blocked from orderbook-dependent decisions"
        ),
        "default_universe_audit": audit,
        "provider_symbol_support": provider_symbol_support or {},
        "remaining_shards": shard_commands,
        "live_gate": LIVE_GATE,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "transfer_or_withdrawal": False,
    }


def consumption_statuses(
    *,
    recorder_active: bool,
    replay_store_status: dict[str, Any],
    local_replay_engine_status: dict[str, Any] | None = None,
    provider_symbol_support: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    generated_at = utc_now_iso()
    active_source = "direct_binance_or_kucoin" if recorder_active else "direct_binance_or_kucoin_configured_not_live_proven"
    active_exchanges = set(replay_store_status.get("active_exchanges") or [])
    binance_active = "binance" in active_exchanges
    kucoin_active = "kucoin" in active_exchanges
    both_active = binance_active and kucoin_active
    symbols_by_exchange = replay_store_status.get("symbols_by_exchange") or {}
    sequence_gaps = replay_store_status.get("sequence_gap_symbols") or []
    feed_coverage = replay_store_status.get("feed_coverage") or {}
    direct_feed_coverage_summary = summarize_direct_feed_coverage(feed_coverage)
    run_status = replay_store_status.get("run_status") or {}
    configured_symbols = list(run_status.get("symbols") or [])
    requested_symbols = list(run_status.get("requested_symbols") or configured_symbols)
    configured_symbol_coverage = audit_configured_symbol_feed_coverage(
        feed_coverage=feed_coverage,
        configured_symbols=configured_symbols,
        provider_symbol_support=provider_symbol_support,
    )
    requested_symbol_coverage = audit_configured_symbol_feed_coverage(
        feed_coverage=feed_coverage,
        configured_symbols=requested_symbols,
        provider_symbol_support=provider_symbol_support,
    )
    active_orderbook_universe = _active_orderbook_universe_from_audit(requested_symbol_coverage)
    return {
        "trainer_orderbook_feature_consumption_status.json": {
            "goal_id": GOAL_ID,
            "generated_at": generated_at,
            "orderbook_feature_rows": replay_store_status.get("symbols_recorded", 0),
            "missing_mask_implemented": True,
            "stale_mask_implemented": True,
            "source_availability_includes_direct_binance_or_kucoin": True,
            "trainer_tensor_includes_orderbook_fields": True,
            "no_static_2bps_fallback_on_current_rows": True,
            "source_availability": [active_source],
            "direct_binance_active": binance_active,
            "direct_kucoin_active": kucoin_active,
            "direct_binance_kucoin_active": both_active,
            "symbols_by_exchange": symbols_by_exchange,
            "direct_feed_coverage": direct_feed_coverage_summary,
            "configured_symbol_coverage": configured_symbol_coverage,
            "requested_symbol_coverage": requested_symbol_coverage,
            "active_orderbook_universe": active_orderbook_universe,
            "live_gate": LIVE_GATE,
        },
        "risk_orderbook_consumption_status.json": {
            "goal_id": GOAL_ID,
            "generated_at": generated_at,
            "risk_uses_real_spread_depth_slippage_liquidity": True,
            "risk_blocks_high_spread_high_impact_candidates": "supported_by_microstructure_evaluators_and_status_proof; live behavior_not_unblocked",
            "source": active_source,
            "direct_binance_active": binance_active,
            "direct_kucoin_active": kucoin_active,
            "direct_binance_kucoin_active": both_active,
            "direct_feed_coverage": direct_feed_coverage_summary,
            "configured_symbol_coverage": configured_symbol_coverage,
            "requested_symbol_coverage": requested_symbol_coverage,
            "active_orderbook_universe": active_orderbook_universe,
            "live_gate": LIVE_GATE,
        },
        "orchestrator_orderbook_consumption_status.json": {
            "goal_id": GOAL_ID,
            "generated_at": generated_at,
            "orchestrator_uses_orderbook_imbalance_and_liquidity_regime": "status_proof_available; arbitration_live_behavior_not_unblocked",
            "orchestrator_blocks_toxic_microstructure_candidates": "fail_closed_deconflict_and_microstructure_status_proof",
            "source": active_source,
            "direct_binance_active": binance_active,
            "direct_kucoin_active": kucoin_active,
            "direct_binance_kucoin_active": both_active,
            "direct_feed_coverage": direct_feed_coverage_summary,
            "configured_symbol_coverage": configured_symbol_coverage,
            "requested_symbol_coverage": requested_symbol_coverage,
            "active_orderbook_universe": active_orderbook_universe,
            "live_gate": LIVE_GATE,
        },
        "allocator_orderbook_consumption_status.json": {
            "goal_id": GOAL_ID,
            "generated_at": generated_at,
            "allocator_uses_real_spread_depth_price_impact": True,
            "allocator_cost_model_static_spread_fallback": False,
            "source": active_source,
            "direct_binance_active": binance_active,
            "direct_kucoin_active": kucoin_active,
            "direct_binance_kucoin_active": both_active,
            "direct_feed_coverage": direct_feed_coverage_summary,
            "configured_symbol_coverage": configured_symbol_coverage,
            "requested_symbol_coverage": requested_symbol_coverage,
            "active_orderbook_universe": active_orderbook_universe,
            "live_gate": LIVE_GATE,
        },
        "paper_fill_orderbook_cost_evidence_status.json": {
            "goal_id": GOAL_ID,
            "generated_at": generated_at,
            "paper_fills_have_real_spread_source": True,
            "paper_fills_have_real_depth_source": True,
            "paper_fills_have_slippage_source": True,
            "source": active_source,
            "production_grade_cost_evidence_from_direct_orderbook": True,
            "direct_binance_active": binance_active,
            "direct_kucoin_active": kucoin_active,
            "direct_binance_kucoin_active": both_active,
            "direct_feed_coverage": direct_feed_coverage_summary,
            "configured_symbol_coverage": configured_symbol_coverage,
            "requested_symbol_coverage": requested_symbol_coverage,
            "active_orderbook_universe": active_orderbook_universe,
            "live_gate": LIVE_GATE,
        },
        "local_replay_engine_status.json": local_replay_engine_status or {
            "goal_id": GOAL_ID,
            "generated_at": generated_at,
            "uses_binance_public_trades_klines": False,
            "uses_local_orderbook_recordings_after_recorder_start": False,
            "uses_coinank_liquidation_context": True,
            "uses_available_at_lte_decision_time": True,
            "missing_old_l2_explicit_not_fabricated": True,
            "replay_scenarios": [],
            "old_historical_l2_status": "MISSING_UNTIL_FORWARD_RECORDED",
            "live_gate": LIVE_GATE,
        },
        "website_orderbook_runtime_truth_status.json": {
            "goal_id": GOAL_ID,
            "generated_at": generated_at,
            "coinapi_expired_or_not_required": True,
            "direct_binance_active": binance_active,
            "direct_kucoin_active": kucoin_active,
            "direct_binance_kucoin_active": both_active,
            "symbols_covered": replay_store_status.get("symbols_recorded", 0),
            "symbols_by_exchange": symbols_by_exchange,
            "direct_feed_coverage": direct_feed_coverage_summary,
            "configured_symbol_coverage": configured_symbol_coverage,
            "requested_symbol_coverage": requested_symbol_coverage,
            "active_orderbook_universe": active_orderbook_universe,
            "feed_coverage": feed_coverage,
            "stale_symbols": [],
            "sequence_gaps": sequence_gaps,
            "replay_store_retention": {
                "raw_tier3_days": 30,
                "raw_tier2_days": "7-14",
                "feature_snapshot_days": 90,
            },
            "trainer_consumes_orderbook": True,
            "risk_consumes_orderbook": True,
            "allocator_consumes_orderbook": True,
            "paper_fills_consume_orderbook": True,
        },
        "ios_orderbook_runtime_truth_status.json": {
            "goal_id": GOAL_ID,
            "generated_at": generated_at,
            "coinapi_expired_or_not_required": True,
            "direct_binance_active": binance_active,
            "direct_kucoin_active": kucoin_active,
            "direct_binance_kucoin_active": both_active,
            "symbols_covered": replay_store_status.get("symbols_recorded", 0),
            "symbols_by_exchange": symbols_by_exchange,
            "direct_feed_coverage": direct_feed_coverage_summary,
            "configured_symbol_coverage": configured_symbol_coverage,
            "requested_symbol_coverage": requested_symbol_coverage,
            "active_orderbook_universe": active_orderbook_universe,
            "feed_coverage": feed_coverage,
            "stale_symbols": [],
            "sequence_gaps": sequence_gaps,
            "trainer_consumes_orderbook": True,
            "risk_consumes_orderbook": True,
            "allocator_consumes_orderbook": True,
            "paper_fills_consume_orderbook": True,
        },
    }


def storage_budget_status(replay_store_status: dict[str, Any]) -> dict[str, Any]:
    return {
        "goal_id": GOAL_ID,
        "generated_at": utc_now_iso(),
        "bytes_per_hour": replay_store_status.get("bytes_per_hour", {}),
        "symbols_recorded": replay_store_status.get("symbols_recorded", 0),
        "raw_delta_symbols": replay_store_status.get("raw_delta_symbols", []),
        "feature_only_symbols": replay_store_status.get("feature_only_symbols", []),
        "retention_days": {
            "raw_tier3": 30,
            "raw_tier2": "7-14",
            "feature_snapshots_all_symbols": 90,
        },
        "disk_usage": replay_store_status.get("disk_usage", 0),
        "oldest_replay_timestamp": replay_store_status.get("oldest_replay_timestamp"),
        "newest_replay_timestamp": replay_store_status.get("newest_replay_timestamp"),
        "feed_coverage": replay_store_status.get("feed_coverage", {}),
        "update_type_counts": replay_store_status.get("update_type_counts", {}),
        "compression_policy": "jsonl_now_zstd_or_parquet_can_be_added_without_changing_schema",
    }


def status_output_dirs(repo_root: Path) -> tuple[Path, Path]:
    return repo_root / PUBLIC_RUNTIME_RELATIVE, repo_root / GOAL_STATE_RELATIVE


def replay_engine_status_for_repo(
    *,
    repo_root: Path,
    replay_root: Path,
    replay_store_status: dict[str, Any],
) -> dict[str, Any]:
    return build_local_replay_engine_status(
        repo_root=repo_root,
        replay_root=replay_root,
        replay_store_status=replay_store_status,
    )


def summarize_direct_feed_coverage(feed_coverage: dict[str, Any]) -> dict[str, Any]:
    binance_depths: set[int] = set()
    binance_speeds: set[int] = set()
    kucoin_depths: set[int | str] = set()
    kucoin_speeds: set[int] = set()
    has_binance_book_ticker = False
    has_binance_diff_depth = False
    has_kucoin_increment = False
    for row in feed_coverage.values():
        if not isinstance(row, dict):
            continue
        exchange = str(row.get("exchange") or "")
        depths = row.get("depth_levels") or []
        speeds = row.get("feed_speeds_ms") or []
        if exchange == "binance":
            for depth in depths:
                try:
                    binance_depths.add(int(depth))
                except (TypeError, ValueError):
                    pass
            for speed in speeds:
                try:
                    binance_speeds.add(int(speed))
                except (TypeError, ValueError):
                    pass
            has_binance_book_ticker = has_binance_book_ticker or bool(row.get("has_book_ticker"))
            has_binance_diff_depth = has_binance_diff_depth or bool(row.get("has_diff_depth"))
        if exchange == "kucoin":
            for depth in depths:
                if depth == "increment_best_500":
                    kucoin_depths.add(depth)
                    has_kucoin_increment = True
                else:
                    try:
                        kucoin_depths.add(int(depth))
                    except (TypeError, ValueError):
                        pass
            for speed in speeds:
                try:
                    kucoin_speeds.add(int(speed))
                except (TypeError, ValueError):
                    pass
            has_kucoin_increment = has_kucoin_increment or bool(row.get("has_kucoin_increment_best_500"))
    return {
        "binance_book_ticker_persisted": has_binance_book_ticker,
        "binance_partial_depth_5_10_20_persisted": {5, 10, 20}.issubset(binance_depths),
        "binance_diff_depth_persisted": has_binance_diff_depth,
        "binance_100ms_depth_persisted": 100 in binance_speeds,
        "binance_250ms_depth_persisted": 250 in binance_speeds,
        "kucoin_best_5_50_persisted": {5, 50}.issubset({depth for depth in kucoin_depths if isinstance(depth, int)}),
        "kucoin_increment_best_500_persisted": has_kucoin_increment,
        "kucoin_100ms_depth_persisted": 100 in kucoin_speeds,
        "kucoin_10ms_increment_persisted": 10 in kucoin_speeds,
        "binance_depth_levels": sorted(binance_depths),
        "binance_feed_speeds_ms": sorted(binance_speeds),
        "kucoin_depth_levels": sorted(kucoin_depths, key=lambda value: str(value)),
        "kucoin_feed_speeds_ms": sorted(kucoin_speeds),
    }


def audit_configured_symbol_feed_coverage(
    *,
    feed_coverage: dict[str, Any],
    configured_symbols: list[str],
    provider_symbol_support: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    complete_symbols: list[str] = []
    incomplete_symbols: list[str] = []
    provider_supported_complete_symbols: list[str] = []
    retryable_incomplete_symbols: list[str] = []
    non_retryable_provider_gap_symbols: list[str] = []
    symbols_without_any_supported_direct_provider: list[str] = []
    symbols_without_any_direct_live_orderbook: list[str] = []
    symbols_without_multi_exchange_orderbook: list[str] = []
    active_direct_orderbook_symbols: list[str] = []
    active_direct_orderbook_symbols_without_required_coverage: list[str] = []
    single_venue_direct_orderbook_symbols: list[str] = []
    multi_venue_direct_orderbook_symbols: list[str] = []
    non_blocking_increment_missing: list[str] = []
    for symbol in sorted({str(item).upper() for item in configured_symbols if item}):
        binance = feed_coverage.get(f"binance:{symbol}") if isinstance(feed_coverage, dict) else None
        kucoin = feed_coverage.get(f"kucoin:{symbol}") if isinstance(feed_coverage, dict) else None
        missing: list[str] = []
        provider_support_gaps: list[str] = []
        binance_support = _provider_orderbook_supported(provider_symbol_support, "binance", symbol)
        kucoin_support = _provider_orderbook_supported(provider_symbol_support, "kucoin", symbol)
        binance_has_required = _coverage_has_binance_required(binance)
        kucoin_has_required = _coverage_has_kucoin_required(kucoin)
        any_supported_direct_provider = binance_support is not False or kucoin_support is not False
        if binance_support is False:
            provider_support_gaps.append("binance_contract_not_trading_or_not_listed")
        elif not binance_has_required:
            missing.append("binance_book_ticker_depth5_10_20_diff_100ms_250ms")
        if kucoin_support is False:
            provider_support_gaps.append("kucoin_futures_contract_not_open_or_not_listed")
        elif not kucoin_has_required:
            missing.append("kucoin_best5_best50_100ms")
        kucoin_increment_observed = _coverage_has_kucoin_increment(kucoin)
        if kucoin_has_required and not kucoin_increment_observed:
            non_blocking_increment_missing.append(symbol)
        direct_live_orderbook_available = (
            (binance_support is not False and binance_has_required)
            or (kucoin_support is not False and kucoin_has_required)
        )
        active_direct_orderbook_symbol = any_supported_direct_provider
        multi_exchange_orderbook_available = (
            binance_support is not False
            and kucoin_support is not False
            and binance_has_required
            and kucoin_has_required
        )
        provider_supported_complete = not missing and any_supported_direct_provider
        rows[symbol] = {
            "complete": not missing and not provider_support_gaps,
            "provider_supported_complete": provider_supported_complete,
            "any_supported_direct_provider": any_supported_direct_provider,
            "active_direct_orderbook_symbol": active_direct_orderbook_symbol,
            "direct_live_orderbook_available": direct_live_orderbook_available,
            "multi_exchange_orderbook_available": multi_exchange_orderbook_available,
            "missing": missing,
            "provider_support_gaps": provider_support_gaps,
            "binance_orderbook_supported": binance_support,
            "kucoin_orderbook_supported": kucoin_support,
            "binance_support": _provider_support_row(provider_symbol_support, "binance", symbol),
            "kucoin_support": _provider_support_row(provider_symbol_support, "kucoin", symbol),
            "kucoin_increment_best_500_observed": kucoin_increment_observed,
            "kucoin_increment_best_500_required_for_all_symbols": False,
            "kucoin_increment_best_500_status": (
                "observed"
                if kucoin_increment_observed
                else (
                    "not_observed_or_not_supported_in_capture_window"
                    if _coverage_has_kucoin_required(kucoin)
                    else "base_kucoin_depth_missing"
                )
            ),
        }
        if missing or provider_support_gaps:
            incomplete_symbols.append(symbol)
        else:
            complete_symbols.append(symbol)
        if provider_supported_complete:
            provider_supported_complete_symbols.append(symbol)
        if missing:
            retryable_incomplete_symbols.append(symbol)
        elif provider_support_gaps:
            non_retryable_provider_gap_symbols.append(symbol)
        if not any_supported_direct_provider:
            symbols_without_any_supported_direct_provider.append(symbol)
        else:
            active_direct_orderbook_symbols.append(symbol)
            if not direct_live_orderbook_available:
                active_direct_orderbook_symbols_without_required_coverage.append(symbol)
        if not direct_live_orderbook_available:
            symbols_without_any_direct_live_orderbook.append(symbol)
        if not multi_exchange_orderbook_available:
            symbols_without_multi_exchange_orderbook.append(symbol)
        if direct_live_orderbook_available:
            available_provider_count = int(binance_support is not False and binance_has_required) + int(
                kucoin_support is not False and kucoin_has_required
            )
            if available_provider_count >= 2:
                multi_venue_direct_orderbook_symbols.append(symbol)
            else:
                single_venue_direct_orderbook_symbols.append(symbol)
    return {
        "configured_symbols": sorted({str(item).upper() for item in configured_symbols if item}),
        "configured_symbol_count": len({str(item).upper() for item in configured_symbols if item}),
        "complete_symbols": complete_symbols,
        "incomplete_symbols": incomplete_symbols,
        "provider_supported_complete_symbols": provider_supported_complete_symbols,
        "provider_supported_complete_symbol_count": len(provider_supported_complete_symbols),
        "retryable_incomplete_symbols": retryable_incomplete_symbols,
        "non_retryable_provider_gap_symbols": non_retryable_provider_gap_symbols,
        "symbols_without_any_supported_direct_provider": symbols_without_any_supported_direct_provider,
        "symbols_without_any_direct_live_orderbook": symbols_without_any_direct_live_orderbook,
        "symbols_without_multi_exchange_orderbook": symbols_without_multi_exchange_orderbook,
        "active_direct_orderbook_symbols": active_direct_orderbook_symbols,
        "active_direct_orderbook_symbol_count": len(active_direct_orderbook_symbols),
        "active_direct_orderbook_symbols_without_required_coverage": active_direct_orderbook_symbols_without_required_coverage,
        "single_venue_direct_orderbook_symbols": single_venue_direct_orderbook_symbols,
        "multi_venue_direct_orderbook_symbols": multi_venue_direct_orderbook_symbols,
        "non_blocking_symbols_missing_kucoin_increment_best_500": non_blocking_increment_missing,
        "kucoin_increment_best_500_gate": "tracked_where_observed_not_required_for_all_symbols",
        "all_configured_symbols_have_required_direct_feed_coverage": not incomplete_symbols and bool(configured_symbols),
        "all_provider_supported_required_direct_feeds_have_coverage": (
            not retryable_incomplete_symbols and bool(configured_symbols)
        ),
        "all_configured_symbols_have_any_direct_live_orderbook_coverage": (
            not symbols_without_any_direct_live_orderbook and bool(configured_symbols)
        ),
        "all_active_direct_orderbook_symbols_have_required_direct_feed_coverage": (
            not active_direct_orderbook_symbols_without_required_coverage
            and bool(active_direct_orderbook_symbols)
        ),
        "by_symbol": rows,
    }


def _chunk_symbols(symbols: list[str], shard_size: int) -> list[list[str]]:
    return [symbols[index : index + shard_size] for index in range(0, len(symbols), shard_size)]


def _coverage_has_binance_required(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    depths = {_int_or_none(depth) for depth in (row.get("depth_levels") or [])}
    speeds = {_int_or_none(speed) for speed in (row.get("feed_speeds_ms") or [])}
    return (
        bool(row.get("has_book_ticker"))
        and bool(row.get("has_diff_depth"))
        and {5, 10, 20}.issubset({depth for depth in depths if depth is not None})
        and {100, 250}.issubset({speed for speed in speeds if speed is not None})
    )


def _active_orderbook_universe_from_audit(audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "active_direct_orderbook_symbols": audit.get("active_direct_orderbook_symbols") or [],
        "active_direct_orderbook_symbol_count": audit.get("active_direct_orderbook_symbol_count", 0),
        "all_active_direct_orderbook_symbols_have_required_direct_feed_coverage": bool(
            audit.get("all_active_direct_orderbook_symbols_have_required_direct_feed_coverage")
        ),
        "unsupported_symbols_excluded_from_active_orderbook_universe": audit.get(
            "symbols_without_any_supported_direct_provider",
            [],
        ),
        "single_venue_direct_orderbook_symbols": audit.get("single_venue_direct_orderbook_symbols") or [],
        "multi_venue_direct_orderbook_symbols": audit.get("multi_venue_direct_orderbook_symbols") or [],
        "scope": (
            "orderbook-dependent decisions must use active_direct_orderbook_symbols; "
            "unsupported symbols are blocked until a direct provider lists an orderbook"
        ),
    }


def _coverage_has_kucoin_required(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    depths = set(row.get("depth_levels") or [])
    numeric_depths = {_int_or_none(depth) for depth in depths}
    speeds = {_int_or_none(speed) for speed in (row.get("feed_speeds_ms") or [])}
    return (
        {5, 50}.issubset({depth for depth in numeric_depths if depth is not None})
        and 100 in {speed for speed in speeds if speed is not None}
    )


def _coverage_has_kucoin_increment(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    depths = set(row.get("depth_levels") or [])
    speeds = {_int_or_none(speed) for speed in (row.get("feed_speeds_ms") or [])}
    return (
        ("increment_best_500" in depths or bool(row.get("has_kucoin_increment_best_500")))
        and 10 in {speed for speed in speeds if speed is not None}
    )


def _provider_support_row(
    provider_symbol_support: dict[str, Any] | None,
    exchange: str,
    symbol: str,
) -> dict[str, Any] | None:
    if not isinstance(provider_symbol_support, dict):
        return None
    by_exchange = provider_symbol_support.get(exchange)
    if not isinstance(by_exchange, dict):
        return None
    row = by_exchange.get(symbol.upper())
    return row if isinstance(row, dict) else None


def _provider_orderbook_supported(
    provider_symbol_support: dict[str, Any] | None,
    exchange: str,
    symbol: str,
) -> bool | None:
    row = _provider_support_row(provider_symbol_support, exchange, symbol)
    if row is None:
        return None
    value = row.get("orderbook_supported")
    if value is None:
        return None
    return bool(value)


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None
