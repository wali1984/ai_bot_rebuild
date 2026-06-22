from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from v2.backend.app.cli import (
    v2_dynamic_93_symbol_runtime_burn_in_edge_and_website_sync as gate,
)


class FakeRedis:
    def __init__(self, store: dict[str, Any]) -> None:
        self.store = store
        self.set_calls: list[tuple[Any, ...]] = []

    def get(self, key: str) -> str | None:
        value = self.store.get(key)
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value)

    def set(self, *args: Any, **kwargs: Any) -> None:
        self.set_calls.append(args)
        raise AssertionError("aggregator must not write Redis")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _make_symbols() -> list[str]:
    return [f"T{i:03d}USDT" for i in range(1, 94)]


def _seed_repo(repo: Path, symbols: list[str]) -> None:
    public = repo / "v2/frontend/public"
    now = "2026-06-04T05:45:00Z"
    _write_json(
        public / "operator_runtime/symbol_universe/latest/symbol_universe_status.json",
        {
            "generated_at": now,
            "discovered_symbols": symbols,
            "training_symbols": symbols,
            "paper_symbols": symbols,
            "live_data_symbols": symbols,
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "execution_live_symbols": [],
        },
    )
    _write_json(
        public
        / "operator_runtime/v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json",
        {
            "generated_utc": now,
            "candidate_count": len(symbols),
            "candidate_state_counts": {"SYMBOL_UNIVERSE_GATE_REQUIRED": len(symbols)},
            "candidates": [
                {
                    "symbol": symbol,
                    "candidate_state": "SYMBOL_UNIVERSE_GATE_REQUIRED",
                    "candidate_reason": "paper gate required",
                    "live_symbol_candidate": False,
                }
                for symbol in symbols
            ],
            "live_gate": "blocked_human_only",
            "live_symbols": [],
        },
    )
    _write_json(
        public
        / "operator_runtime/v2_dynamic_symbol_discovery/latest/dynamic_symbol_discovery_status.json",
        {
            "generated_utc": now,
            "coingecko_status": {"generated_utc": now, "source_status_counts": {"API_OK": 1}},
            "surf_status": {"generated_utc": now, "source_status_counts": {"API_OK": 3}},
            "coinglass_status": {
                "generated_utc": now,
                "source_status_counts": {"API_PLAN_BLOCKED_401_UPGRADE_PLAN": 1},
            },
            "live_gate": "blocked_human_only",
            "live_symbols": [],
        },
    )
    _write_json(
        public
        / "operator_runtime/v2_trainer_training_live_loop/latest/v2_trainer_training_live_loop_status.json",
        {
            "generated_utc": now,
            "classification": "V2_TRAINER_TRAINING_LIVE_OK",
            "row_count": 23038,
            "train_rows": 299,
            "validation_rows": 82,
            "trained_model_available": True,
        },
    )
    post_hoc = {
        "generated_at": now,
        "go_no_go": "V2_POST_HOC_REPLAY_OUTCOME_MINER_READY",
        "symbols": symbols,
        "bundles_total": len(symbols),
        "label_counts": {"false_negative": len(symbols)},
        "windows_filled": {"5m": len(symbols)},
        "evaluator_metric_summary": {
            "verdict": "EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED",
            "verdict_reason": "operator thresholds required",
            "after_cost_pnl_delta": -8.1,
            "after_cost_ci_lower_bps": -10.2,
            "after_cost_ci_upper_bps": -5.5,
            "false_positive_rate": 0.0,
            "false_negative_rate": 1.0,
            "v2_vs_legacy_action_match_rate": None,
            "v2_hold_due_checkpoint_count": 0,
            "v2_hold_due_strict_gate_count": 0,
        },
    }
    _write_json(public / "v2_post_hoc_replay_outcome_miner/latest/post_hoc_replay_outcome_status.json", post_hoc)
    _write_json(public / "v2_post_hoc_replay_outcome_miner/latest/operator_dashboard_payload.json", post_hoc)
    _write_json(
        public / "v2_post_hoc_replay_outcome_miner/latest/edge_metrics_summary.json",
        {"generated_at": now, "metric_summary": post_hoc["evaluator_metric_summary"]},
    )
    bundle_path = public / "v2_post_hoc_replay_outcome_miner/latest/replay_outcome_bundles.jsonl"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(
        "".join(
            json.dumps(
                {
                    "symbol": symbol,
                    "label": "false_negative",
                    "future_outcomes": {"5m": {"after_cost_return_bps": -8.1}},
                    "paper_gate_decision": {"paper_fill_gate_block_reasons": []},
                },
                sort_keys=True,
            )
            + "\n"
            for symbol in symbols
        ),
        encoding="utf-8",
    )
    _write_json(
        public / "v2_native_edge_proof/latest/operator_dashboard_payload.json",
        {
            "generated_at": now,
            "sample_count": len(symbols),
            "verdict": "EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED",
        },
    )
    _write_json(
        public / "v2_website_data_alignment_and_control_plane/latest/operator_dashboard_payload.json",
        {"generated_utc": now, "go_no_go": "V2_WEBSITE_DATA_ALIGNMENT_AND_CONTROL_PLANE_READY"},
    )
    for provider, counts in {
        "v2_nansen_altdata_client/latest/v2_nansen_altdata_status.json": {"API_OK": 1},
        "v2_lunarcrush_altdata_client/latest/v2_lunarcrush_altdata_status.json": {
            "API_PAYMENT_REQUIRED_402": len(symbols)
        },
    }.items():
        _write_json(
            public / "operator_runtime" / provider,
            {
                "generated_utc": now,
                "provider": provider,
                "source_status_counts": counts,
                "successful_symbol_count": 0,
                "symbol_count": len(symbols),
                "key_present": True,
                "network_call_attempted": True,
                "live_gate": "blocked_human_only",
                "live_symbols": [],
                "writes_legacy_redis": False,
                "writes_exchange_orders": False,
            },
        )
    _write_json(
        public / "operator_runtime/v2_coinapi_rest_ingestor/latest/v2_coinapi_rest_ingestor_status.json",
        {
            "generated_utc": now,
            "classification": "V2_COINAPI_REST_OK",
            "symbols": symbols,
            "fetch": {"symbols_fetched": len(symbols), "symbols_requested": len(symbols)},
            "orderbooks_present_count": len(symbols),
            "v2_redis_keys_written_count": len(symbols) * 3,
            "live_gate": "blocked_human_only",
            "live_symbols": [],
        },
    )
    _write_json(
        public / "operator_runtime/v2_coinapi_wsds/latest/v2_coinapi_wsds_status.json",
        {
            "generated_utc": now,
            "classification": "V2_COINAPI_WSDS_CONNECTED",
            "stream_connected": True,
            "symbols": symbols,
            "symbols_count": len(symbols),
            "stats": {"messages_received": 500, "snapshots_written": 200, "microfeatures_written": 600},
            "live_gate": "blocked_human_only",
            "live_symbols": [],
        },
    )
    _write_json(
        public / "operator_runtime/v2_kucoin_ingestor/latest/v2_kucoin_ingestor_status.json",
        {
            "generated_utc": now,
            "classification": "NATIVE_V2_PUBLIC_REST_OK",
            "public_rest_fetch": {"symbols_fetched": len(symbols), "symbols_requested": len(symbols)},
            "symbols_v2": symbols,
            "v2_redis_keys_written_count": len(symbols) * 4,
            "live_gate": "blocked_human_only",
            "live_symbols": [],
        },
    )
    _write_json(
        public / "operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json",
        {
            "generated_utc": now,
            "source": "V2_COINANK_AND_LIQUIDATION_BRIDGE",
            "symbols": symbols,
            "v2_redis_feature_input": {"symbols_requested": len(symbols), "symbols_with_any_input": len(symbols)},
            "v2_redis_global_keys_written_count": 34,
            "global_aggregate_result": {"n_symbols_observed": len(symbols), "total_oi": 1000.0},
            "live_gate": "blocked_human_only",
            "live_symbols": [],
        },
    )
    symbols_page = repo / "v2/frontend/src/pages/symbols/index.tsx"
    symbols_page.parent.mkdir(parents=True, exist_ok=True)
    symbols_page.write_text(gate.LANE_ID, encoding="utf-8")


def _seed_redis(symbols: list[str]) -> FakeRedis:
    now = "2026-06-04T05:45:00Z"
    store: dict[str, Any] = {
        "v2:altdata:coingecko:status": {
            "generated_utc": now,
            "source_status_counts": {"API_OK": 1},
            "successful_symbol_count": 81,
            "symbol_count": 81,
        },
        "v2:altdata:surf:status": {
            "generated_utc": now,
            "source_status_counts": {"API_OK": 3},
            "successful_symbol_count": 3,
            "symbol_count": 3,
        },
        "v2:altdata:coinglass:status": {
            "generated_utc": now,
            "source_status_counts": {"API_PLAN_BLOCKED_401_UPGRADE_PLAN": 1},
            "successful_symbol_count": 0,
            "symbol_count": 0,
        },
    }
    for symbol in symbols:
        store[f"v2:market:prices:{symbol}"] = {"symbol": symbol, "fetched_utc": now}
        store[f"v2:features:latest:{symbol}:1m"] = {
            "symbol": symbol,
            "generated_at": now,
            "real_feature_count": 20,
            "missing_feature_count": 0,
            "stale_feature_flags": [],
        }
        store[f"v2:features:ta:{symbol}:1m"] = {"symbol": symbol, "generated_utc": now}
        store[f"v2:prediction:{symbol}:1m"] = {
            "symbol": symbol,
            "generated_utc": now,
            "trainer_source": "V2_NATIVE_RL_CORE",
            "trainer_online_mode": "V2_NATIVE_RL_CORE_WITH_LEGACY_CHECKPOINT_EVIDENCE",
            "checkpoint_blocker": "OPERATOR_DECISION_REQUIRED_NATIVE_TRAINER_CHECKPOINT",
            "confidence_calibrated": 0.6,
            "expected_move_after_cost_bps": -8.1,
            "paper_fill_gate_status": "BLOCKED_BASELINE_OR_CONTRACT_ONLY",
            "paper_fill_allowed": False,
            "paper_fill_gate_block_reasons": ["live_gate_blocked_human_only"],
        }
        store[f"v2:altdata:symbol_score:{symbol}"] = {
            "generated_utc": now,
            "input_presence": {"coingecko": True, "surf": False, "coinglass": False},
            "missing_provider_flags": ["MISSING_COINGLASS"],
        }
        store[f"v2:paper:position_history:{symbol}"] = {
            "generated_utc": now,
            "position_state": "flat",
            "accepted_intent_count": 0,
            "held_intent_count": 1,
        }
        store[f"v2:paper:shadow_outcome:{symbol}"] = {
            "generated_utc": now,
            "decision_label": "HELD_OUTCOME_ONLY",
            "block_reason": "live_gate_blocked_human_only",
        }
    return FakeRedis(store)


def test_dynamic_93_gate_emits_required_status_files_and_blocks_unproven_edge(tmp_path: Path) -> None:
    symbols = _make_symbols()
    _seed_repo(tmp_path, symbols)
    redis = _seed_redis(symbols)

    payload = gate.run_once(repo_root=tmp_path, redis_client_override=redis, write_files=True)

    assert payload["go_no_go"] == gate.GO_NO_GO_BLOCKED
    assert payload["summary"]["dynamic_symbol_count"] == 93
    assert payload["summary"]["edge_proven"] is False
    assert payload["summary"]["primary_live_recommendation"] == "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN"
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["execution_live_symbols"] == []
    assert payload["approves_live"] is False
    assert payload["approves_canary"] is False
    assert redis.set_calls == []

    paths = gate.default_paths(tmp_path)
    for required in [
        "v2_dynamic_93_symbol_runtime_burn_in_status.json",
        "v2_dynamic_93_trainer_quality_status.json",
        "v2_dynamic_93_edge_recompute_status.json",
        "v2_dynamic_provider_contribution_status.json",
        "v2_dynamic_website_sync_status.json",
        "v2_dynamic_live_readiness_recompute_status.json",
        "operator_dashboard_payload.json",
        "GO_NO_GO.md",
    ]:
        assert (paths.public_dir / required).exists(), required
        assert (paths.worklog_dir / required).exists(), required

    assert (paths.public_dir / "GO_NO_GO.md").read_text().strip() == gate.GO_NO_GO_BLOCKED
    provider_status = json.loads((paths.public_dir / "v2_dynamic_provider_contribution_status.json").read_text())
    assert provider_status["paid_or_plan_blockers_visible"]["coinglass"] == "API_PLAN_BLOCKED_401_UPGRADE_PLAN"
    assert provider_status["paid_or_plan_blockers_visible"]["lunarcrush"] == "API_PAYMENT_REQUIRED_402"
    provider_rows = {row["provider"]: row for row in provider_status["provider_rows"]}
    assert provider_rows["kucoin"]["symbol_count"] == len(symbols)
    assert provider_rows["kucoin"]["successful_symbol_count"] == len(symbols)
    assert provider_rows["coinapi_rest"]["symbol_count"] == len(symbols)
    assert provider_rows["coinapi_wsds"]["symbol_count"] == len(symbols)
    assert provider_rows["coinank"]["symbol_count"] == len(symbols)
    assert provider_rows["coinank"]["status"] == "V2_COINANK_GLOBAL_AGGREGATE_OK"
    assert provider_status["provider_presence_counts_by_symbol"]["kucoin"] == len(symbols)
    assert provider_status["provider_presence_counts_by_symbol"]["coinapi_rest"] == len(symbols)
    assert provider_status["provider_presence_counts_by_symbol"]["coinapi_wsds"] == len(symbols)
    assert provider_status["provider_presence_counts_by_symbol"]["coinank"] == len(symbols)
    website_status = json.loads((paths.public_dir / "v2_dynamic_website_sync_status.json").read_text())
    assert website_status["symbols_page_reads_dynamic_93_payload"] is True
