from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli.symbol_universe_public_payload import build_payload
from v2.backend.app.services.symbol_universe.service import LEGACY_ACTIVE_SYMBOLS_25


def _write_status(root: Path, worker: str, payload: dict[str, object]) -> None:
    path = root / "v2/frontend/public/operator_runtime" / worker / "latest" / f"{worker}_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _write_portfolio(root: Path, payload: dict[str, object]) -> None:
    path = root / "v2/frontend/public/operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def test_payload_preserves_symbol_roles_without_live_symbols(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        "v2_trainer_bridge",
        {
            "discovered_symbols": ["BTCUSDT", "ETHUSDT", "COINANK_ONLY_USDT"],
            "dynamic_discovered_symbols": ["BTCUSDT", "ETHUSDT", "COINANK_ONLY_USDT"],
            "observed_symbols": ["BTCUSDT"],
            "training_symbols": ["BTCUSDT"],
            "paper_symbols": ["BTCUSDT"],
            "binance_usdm_confirmed_symbols": ["BTCUSDT", "ETHUSDT"],
        },
    )

    payload = build_payload(tmp_path, generated_at="2026-05-14T10:00:00Z")

    assert payload["generated_at"] == "2026-05-14T10:00:00Z"
    assert payload["symbol_universe_contract"] == "SYMBOL_UNIVERSE_CONTRACT_REQUIRED"
    assert payload["legacy_active_symbols"] == sorted(LEGACY_ACTIVE_SYMBOLS_25)
    assert payload["legacy_active_symbols_are_full_universe"] is False
    assert payload["discovered_symbols"] == ["BTCUSDT", "COINANK_ONLY_USDT", "ETHUSDT"]
    assert payload["observed_symbols"] == ["BTCUSDT"]
    assert payload["training_symbols"] == ["BTCUSDT"]
    assert payload["paper_symbols"] == ["BTCUSDT"]
    assert payload["live_symbols"] == []
    assert payload["live_gate"] == "blocked_human_only"


def test_authoritative_legacy_scopes_prefer_majors_without_changing_membership(
    tmp_path: Path,
) -> None:
    requested = ["XRPUSDT", "SOLUSDT", "ETHUSDT", "BTCUSDT"]
    _write_status(
        tmp_path,
        "v2_scope_source",
        {
            "discovered_symbols": [*requested, "DOGEUSDT"],
            "training_symbols": requested,
            "paper_symbols": requested,
            "binance_usdm_confirmed_symbols": [*requested, "DOGEUSDT"],
        },
    )

    payload = build_payload(tmp_path)

    assert payload["adaptive_scope_activation"]["active"] is False
    assert payload["training_symbols"] == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "XRPUSDT",
    ]
    assert payload["paper_symbols"] == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "XRPUSDT",
    ]
    assert set(payload["training_symbols"]) == set(requested)
    assert set(payload["paper_symbols"]) == set(requested)


def test_training_or_paper_scope_matching_all_discovered_is_rejected(tmp_path: Path) -> None:
    discovered = ["BTCUSDT", "ETHUSDT"]
    _write_status(
        tmp_path,
        "v2_bad_scope",
        {
            "discovered_symbols": discovered,
            "training_symbols": discovered,
            "paper_symbols": discovered,
            "binance_usdm_confirmed_symbols": discovered,
        },
    )

    payload = build_payload(tmp_path)

    assert payload["training_symbols"] == []
    assert payload["paper_symbols"] == []
    assert payload["train_all_discovered_symbols"] is False
    assert payload["trade_all_discovered_symbols"] is False
    assert "requested_scope_matches_or_contains_all_discovered_symbols" in payload["symbol_universe_payload_evidence_gaps"]


def test_coinank_only_symbols_are_not_directly_tradable(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        "v2_coinank",
        {
            "discovered_symbols": ["BTCUSDT", "COINANK_ONLY_USDT"],
            "paper_symbols": ["BTCUSDT", "COINANK_ONLY_USDT"],
            "binance_usdm_confirmed_symbols": ["BTCUSDT"],
        },
    )

    payload = build_payload(tmp_path)

    assert payload["paper_symbols"] == []
    assert "COINANK_ONLY_USDT" in payload["rejected_paper_symbols"]
    assert payload["coinank_symbols_directly_tradable"] is False
    assert payload["coinank_symbols_tradability"] == "market_intelligence_only_until_binance_usdm_confirmed"


def test_active_paper_position_enters_runtime_scopes_when_binance_tradable(
    tmp_path: Path,
) -> None:
    _write_status(
        tmp_path,
        "v2_dynamic_symbol_discovery",
        {
            "discovered_symbols": ["BTCUSDT", "ETHUSDT"],
            "training_symbols": ["BTCUSDT"],
            "paper_symbols": ["BTCUSDT"],
            "binance_usdm_confirmed_symbols": ["BTCUSDT"],
            "binance_usdm_tradable_symbols": ["BTCUSDT", "ETHUSDT", "BASUSDT"],
        },
    )
    _write_portfolio(
        tmp_path,
        {
            "open_positions": [
                {
                    "symbol": "BASUSDT",
                    "open_position": True,
                    "paper_session_id": "paper_3000_current",
                }
            ]
        },
    )

    payload = build_payload(tmp_path)

    assert "BASUSDT" in payload["active_paper_position_symbols"]
    assert "BASUSDT" in payload["discovered_symbols"]
    assert "BASUSDT" in payload["observed_symbols"]
    assert "BASUSDT" in payload["training_symbols"]
    assert "BASUSDT" in payload["paper_symbols"]
    assert payload["live_data_symbols"] == ["BASUSDT"]
    assert "BASUSDT" not in payload["rejected_paper_symbols"]


def _wide_tradable(*extra: str) -> list[str]:
    # Exchange-wide TRADING list stand-in (authority requires >=100 symbols).
    return sorted({f"W{i}USDT" for i in range(120)} | set(extra))


def test_fresh_exchange_tradable_authority_prunes_delisted_confirmed_symbols(tmp_path: Path) -> None:
    # 2026-07-16 incident shape: a stale worker payload keeps confirming a
    # delisted contract (IPUSDT) that the fresh exchange-wide TRADING list no
    # longer contains; the sticky union must be pruned by the dated authority.
    import datetime as dt

    fresh = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_status(
        tmp_path,
        "v2_stale_lineage_worker",
        {
            "discovered_symbols": ["BTCUSDT", "IPUSDT"],
            "training_symbols": ["BTCUSDT", "IPUSDT"],
            "binance_usdm_confirmed_symbols": ["BTCUSDT", "IPUSDT"],
        },
    )
    _write_status(
        tmp_path,
        "v2_dynamic_symbol_discovery",
        {
            "generated_utc": fresh,
            "discovered_symbols": ["BTCUSDT", "ETHUSDT"],
            "training_symbols": ["BTCUSDT"],
            "binance_usdm_confirmed_symbols": ["BTCUSDT"],
            "binance_usdm_tradable_symbols": _wide_tradable("BTCUSDT", "ETHUSDT"),
        },
    )

    payload = build_payload(tmp_path)

    assert "IPUSDT" not in payload["binance_usdm_confirmed_symbols"]
    assert "BTCUSDT" in payload["binance_usdm_confirmed_symbols"]
    assert payload["binance_usdm_delisted_pruned_symbols"] == ["IPUSDT"]
    assert "IPUSDT" not in payload["training_symbols"]
    assert "IPUSDT" in payload["rejected_training_symbols"]
    authority = payload["binance_usdm_tradability_authority"]
    assert authority is not None
    assert authority["authority_key"] == "binance_usdm_tradable_symbols"
    assert "v2_dynamic_symbol_discovery" in authority["source_path"]
    assert "symbols" not in authority  # provenance only, not another sticky list


def test_undated_or_stale_tradable_list_cannot_prune(tmp_path: Path) -> None:
    # An undated exchange list cannot assert *current* tradability: the union
    # is kept (fail open) and the payload records the missing authority.
    _write_status(
        tmp_path,
        "v2_stale_lineage_worker",
        {
            "discovered_symbols": ["BTCUSDT", "IPUSDT"],
            "training_symbols": ["BTCUSDT"],
            "binance_usdm_confirmed_symbols": ["BTCUSDT", "IPUSDT"],
        },
    )
    _write_status(
        tmp_path,
        "v2_dynamic_symbol_discovery",
        {
            # no generated_* timestamp
            "binance_usdm_tradable_symbols": _wide_tradable("BTCUSDT"),
        },
    )

    payload = build_payload(tmp_path)

    assert "IPUSDT" in payload["binance_usdm_confirmed_symbols"]
    assert payload["binance_usdm_delisted_pruned_symbols"] == []
    assert payload["binance_usdm_tradability_authority"] is None
    assert (
        "binance_usdm_tradability_authority_missing_or_stale_confirmed_union_unpruned"
        in payload["symbol_universe_payload_evidence_gaps"]
    )


def test_small_scoped_tradable_list_is_not_an_exchange_authority(tmp_path: Path) -> None:
    # A dated but tiny (scoped/broken) tradable list must not collapse the
    # universe: authority requires an exchange-wide symbol count.
    import datetime as dt

    fresh = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write_status(
        tmp_path,
        "v2_scoped_worker",
        {
            "generated_utc": fresh,
            "binance_usdm_confirmed_symbols": ["BTCUSDT", "ETHUSDT", "IPUSDT"],
            "binance_usdm_tradable_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        },
    )

    payload = build_payload(tmp_path)

    assert "IPUSDT" in payload["binance_usdm_confirmed_symbols"]
    assert payload["binance_usdm_delisted_pruned_symbols"] == []
    assert payload["binance_usdm_tradability_authority"] is None


def _adaptive_evidence(symbol: str, *, proven_oos: bool = False) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": symbol,
        "exchange_confirmed": True,
        "candle_final": True,
        "candle_close_time": "2026-07-20T05:05:00Z",
        "feature_cutoff": "2026-07-20T05:05:00Z",
        "event_time": "2026-07-20T05:05:00.100Z",
        "ingested_at": "2026-07-20T05:05:00.200Z",
        "available_at": "2026-07-20T05:05:00.200Z",
        "market_event_time": "2026-07-20T05:09:30Z",
        "market_ingested_at": "2026-07-20T05:09:30.050Z",
        "market_available_at": "2026-07-20T05:09:30.050Z",
        "generated_at": "2026-07-20T05:09:50Z",
        "training_data_ready": True,
        "closed_candle_count": 100,
        "market_data_coverage_ratio": 1.0,
        "closed_quote_volume_usd": 100_000_000.0,
        "spread_bps": 0.5,
        "top_book_depth_usd": 500_000.0,
        "realized_volatility_bps": 50.0,
        "absolute_move_bps": 100.0,
    }
    if proven_oos:
        row.update(
            {
                "validation_sample_count": 90,
                "after_cost_expectancy_bps": 12.0,
                "after_cost_ci_lower_bps": 5.0,
                "validation_out_of_sample": True,
                "validation_after_cost": True,
                "validation_leakage_free": True,
                "validation_cutoff": "2026-07-20T04:00:00Z",
                "validation_event_time": "2026-07-20T04:00:01Z",
                "validation_ingested_at": "2026-07-20T04:00:02Z",
                "validation_available_at": "2026-07-20T04:00:03Z",
                "validation_generated_at": "2026-07-20T04:00:04Z",
            }
        )
    return row


def _adaptive_runtime_evidence(*rows: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "v2_adaptive_symbol_selection_runtime_evidence_v1",
        "decision_time": "2026-07-20T05:10:00Z",
        "evidence_rows": list(rows),
        "metrics": {"evidence_row_count": len(rows)},
        "source_contract": {
            "opportunity_and_volume": "canonical_finalized_5m_candles_only"
        },
    }


def test_adaptive_scopes_publish_shadow_only_by_default(tmp_path: Path) -> None:
    _write_status(
        tmp_path,
        "v2_scope_source",
        {
            "discovered_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            "training_symbols": ["BTCUSDT"],
            "paper_symbols": ["BTCUSDT"],
            "binance_usdm_confirmed_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        },
    )

    payload = build_payload(
        tmp_path,
        generated_at="2026-07-20T05:10:01Z",
        adaptive_runtime_evidence=_adaptive_runtime_evidence(
            _adaptive_evidence("BTCUSDT"),
            _adaptive_evidence("ETHUSDT"),
        ),
    )

    assert payload["training_symbols"] == ["BTCUSDT"]
    assert payload["paper_symbols"] == ["BTCUSDT"]
    assert payload["adaptive_training_selected_symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert payload["adaptive_paper_new_entry_symbols"] == []
    activation = payload["adaptive_scope_activation"]
    assert activation["active"] is False
    assert activation["activation_blocked_reason"] == (
        "default_off_requires_explicit_operator_activation"
    )
    assert payload["adaptive_guaranteed_1000x_claim"] is False
    assert payload["adaptive_clock_contract"] == {
        "selection_decision_time": "2026-07-20T05:10:00Z",
        "publisher_generated_at": "2026-07-20T05:10:01Z",
        "selection_decision_precedes_publisher_generation": True,
        "decision_time_is_not_generated_at": True,
    }


def test_activation_request_is_blocked_until_scope_aware_consumers_are_bound(
    tmp_path: Path,
) -> None:
    _write_status(
        tmp_path,
        "v2_scope_source",
        {
            "discovered_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            "training_symbols": ["BTCUSDT"],
            "paper_symbols": ["BTCUSDT"],
            "binance_usdm_confirmed_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        },
    )

    payload = build_payload(
        tmp_path,
        generated_at="2026-07-20T05:10:01Z",
        adaptive_runtime_evidence=_adaptive_runtime_evidence(
            _adaptive_evidence("BTCUSDT", proven_oos=True),
            _adaptive_evidence("ETHUSDT"),
        ),
        activate_adaptive_scopes=True,
    )

    assert payload["training_symbols"] == ["BTCUSDT"]
    assert payload["paper_symbols"] == ["BTCUSDT"]
    activation = payload["adaptive_scope_activation"]
    assert activation["requested"] is True
    assert activation["scope_aware_consumers_bound"] is False
    assert activation["active"] is False
    assert activation["activation_blocked_reason"] == (
        "scope_aware_training_paper_and_position_management_consumers_not_bound"
    )


def test_explicit_activation_replaces_authoritative_scopes_and_keeps_open_positions_management_only(
    tmp_path: Path,
) -> None:
    _write_status(
        tmp_path,
        "v2_scope_source",
        {
            "discovered_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            "training_symbols": ["BTCUSDT"],
            "paper_symbols": ["BTCUSDT"],
            "binance_usdm_confirmed_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        },
    )
    _write_portfolio(
        tmp_path,
        {
            "open_positions": [
                {"symbol": "SOLUSDT", "open_position": True, "position_state": "long_open"}
            ]
        },
    )

    payload = build_payload(
        tmp_path,
        generated_at="2026-07-20T05:10:01Z",
        adaptive_runtime_evidence=_adaptive_runtime_evidence(
            _adaptive_evidence("BTCUSDT", proven_oos=True),
            _adaptive_evidence("ETHUSDT"),
        ),
        activate_adaptive_scopes=True,
        adaptive_scope_consumers_bound=True,
    )

    assert payload["training_symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert payload["paper_symbols"] == ["BTCUSDT"]
    assert payload["live_data_symbols"] == ["SOLUSDT"]
    assert payload["active_position_management_symbols"] == ["SOLUSDT"]
    assert "SOLUSDT" not in payload["training_symbols"]
    assert "SOLUSDT" not in payload["paper_symbols"]
    assert payload["adaptive_scope_activation"]["active"] is True
    assert payload["adaptive_scope_activation"][
        "retained_open_positions_are_new_entry_eligible"
    ] is False


def test_activation_cannot_admit_evidence_outside_current_exchange_candidate_set(
    tmp_path: Path,
) -> None:
    _write_status(
        tmp_path,
        "v2_scope_source",
        {
            "discovered_symbols": ["BTCUSDT"],
            "training_symbols": ["BTCUSDT"],
            "paper_symbols": ["BTCUSDT"],
            "binance_usdm_confirmed_symbols": ["BTCUSDT"],
        },
    )

    payload = build_payload(
        tmp_path,
        generated_at="2026-07-20T05:10:01Z",
        adaptive_runtime_evidence=_adaptive_runtime_evidence(
            _adaptive_evidence("FAKEUSDT", proven_oos=True),
        ),
        activate_adaptive_scopes=True,
        adaptive_scope_consumers_bound=True,
    )

    assert payload["adaptive_scope_activation"]["active"] is True
    assert payload["training_symbols"] == []
    assert payload["paper_symbols"] == []
    explanation = payload["adaptive_symbol_selection"]["symbol_explanations"][
        "FAKEUSDT"
    ]
    assert explanation["training_eligible"] is False
    assert "exchange_not_confirmed" in explanation["training_blockers"]
    assert (
        "source:symbol_not_in_current_exchange_confirmed_discovered_candidate_set"
        in explanation["training_blockers"]
    )
