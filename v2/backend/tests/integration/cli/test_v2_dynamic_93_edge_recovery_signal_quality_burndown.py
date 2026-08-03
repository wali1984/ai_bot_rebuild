from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.cli import v2_dynamic_93_edge_recovery_signal_quality_burndown as gate


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
        raise AssertionError("burndown gate must not write Redis")


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
            "generated_utc": now,
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
        public / "operator_runtime/v2_public_intel_free_tier/latest/v2_public_intel_free_tier_status.json",
        {
            "generated_utc": now,
            "go_no_go": "V2_PUBLIC_INTEL_FREE_TIER_LIVE_OK",
            "symbol_count": len(symbols),
            "successful_symbol_count": len(symbols),
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "execution_live_symbols": [],
        },
    )
    _write_json(
        public / "operator_runtime/v2_trainer_training_live_loop/latest/v2_trainer_training_live_loop_status.json",
        {
            "generated_utc": now,
            "classification": "V2_TRAINER_TRAINING_LIVE_OK",
            "row_count": 23038,
            "train_rows": 299,
            "validation_rows": 82,
            "trained_model_available": True,
        },
    )
    _write_json(
        public / "operator_runtime/v2_paper_execution_worker/latest/v2_paper_execution_worker_status.json",
        {"generated_utc": now, "denials_breakdown": {"deny_default": 1}},
    )
    _write_json(
        public / "operator_runtime/paper_online/latest/current_risk_decisions.json",
        {"generated_at": now, "decisions": []},
    )
    post_hoc = {
        "generated_at": now,
        "go_no_go": "V2_POST_HOC_REPLAY_OUTCOME_MINER_READY",
        "symbols": symbols,
        "bundles_total": len(symbols),
        "label_counts": {"correct_no_trade": len(symbols)},
        "windows_filled": {"5m": len(symbols)},
        "evaluator_metric_summary": {
            "verdict": "EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED",
            "after_cost_pnl_delta": -9.0,
            "after_cost_ci_lower_bps": -11.0,
            "after_cost_ci_upper_bps": -7.0,
        },
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }
    _write_json(public / "v2_post_hoc_replay_outcome_miner/latest/post_hoc_replay_outcome_status.json", post_hoc)
    _write_json(public / "v2_post_hoc_replay_outcome_miner/latest/edge_metrics_summary.json", {"metric_summary": post_hoc["evaluator_metric_summary"]})
    bundle_path = public / "v2_post_hoc_replay_outcome_miner/latest/replay_outcome_bundles.jsonl"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for index, symbol in enumerate(symbols):
        after_cost = 4.0 if index < 2 else -9.0
        lines.append(
            json.dumps(
                {
                    "symbol": symbol,
                    "side": "long",
                    "label": "false_negative" if after_cost > 0 else "correct_no_trade",
                    "future_outcomes": {"5m": {"after_cost_return_bps": after_cost, "drawdown_bps": abs(after_cost)}},
                    "trainer_output": {
                        "selected_action": "long",
                        "confidence_calibrated": 0.8,
                        "expected_move_after_cost_bps": 12.0,
                    },
                    "paper_fill_allowed": False,
                    "paper_gate_decision": {"paper_fill_allowed": False, "paper_fill_gate_block_reasons": []},
                    "risk_decision": {
                        "pre_trade_allowed": True,
                        "fee_gate_allowed": index % 10 != 0,
                        "fee_gate_reason": "BLOCKED_BY_FEE_RATIO" if index % 10 == 0 else "ALLOWED",
                        "churn_blocked": False,
                    },
                    "paper_intent": {"decision": "PAPER_INTENT_OBSERVED", "symbol": symbol, "side": "long"},
                },
                sort_keys=True,
            )
            + "\n"
        )
    bundle_path.write_text("".join(lines), encoding="utf-8")
    for page in [
        "replay/index.tsx",
        "trainer-admin/index.tsx",
        "trainer-prediction-monitor/index.tsx",
        "symbols/index.tsx",
        "market-intelligence/index.tsx",
        "live-readiness/index.tsx",
        "paper-trading/index.tsx",
    ]:
        page_path = repo / "v2/frontend/src/pages" / page
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(f"{gate.LANE_ID} EdgeRecoveryQualityPanel", encoding="utf-8")


def _seed_redis(symbols: list[str]) -> FakeRedis:
    now = "2026-06-04T05:45:00Z"
    store: dict[str, Any] = {}
    for index, symbol in enumerate(symbols):
        store[f"v2:features:latest:{symbol}:1m"] = {
            "generated_at": now,
            "feature_freshness_state": "CURRENT",
            "features": {
                "ret_pct": 0.1 if index % 2 == 0 else -0.1,
                "htf_ret_pct": 0.1,
                "ema_12": 12.0,
                "ema_26": 10.0,
                "rsi_14": 55.0,
                "htf_rsi_14": 52.0,
                "macd_hist": 1.0,
                "range_pct": 0.25,
                "funding_rate": -0.001,
                "oi_change_pct": 0.1,
                "depth_imbalance": 0.2,
            },
        }
        store[f"v2:prediction:{symbol}:1m"] = {
            "generated_utc": now,
            "confidence_calibrated": 0.8,
            "expected_move_after_cost_bps": 12.0,
            "selected_action": "long",
        }
        store[f"v2:altdata:public_intel:symbol:{symbol}"] = {
            "generated_utc": now,
            "public_intel_score": 0.9 - index / 200,
            "defillama_liquidity_score": 0.8,
            "defillama_tvl_momentum_score": 0.7,
            "news_attention_score": 0.6,
            "news_sentiment_score": 0.4,
            "fear_greed_score": 0.2,
            "btc_mempool_pressure_score": 0.1 if index == 0 else None,
        }
        store[f"v2:altdata:symbol_score:{symbol}"] = {
            "generated_utc": now,
            "altdata_symbol_score": 0.7 - index / 300,
            "public_intel_score": 0.9 - index / 200,
            "input_presence": {"public_intel": True, "coingecko": True},
            "missing_provider_flags": [],
        }
    return FakeRedis(store)


def test_edge_recovery_burndown_writes_required_artifacts_and_stays_blocked(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    symbols = _make_symbols()
    _seed_repo(tmp_path, symbols)
    redis = _seed_redis(symbols)
    monkeypatch.setattr(gate, "_now", lambda: datetime(2026, 6, 4, 5, 50, tzinfo=timezone.utc))

    payload = gate.run_once(repo_root=tmp_path, redis_client_override=redis, write_files=True)

    assert payload["go_no_go"] == gate.GO_NO_GO_BLOCKED
    assert payload["summary"]["symbol_count"] == 93
    assert payload["summary"]["pre_filter_after_cost_expectancy_bps"] < 0
    assert payload["edge_recompute_after_quality_fixes"]["negative_after_cost_expectancy_visible"] is True
    assert payload["edge_recompute_after_quality_fixes"]["live_readiness_recommendation"] in {
        "BLOCK_LIVE_MODEL_SIGNAL_QUALITY_NOT_READY",
        "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
    }
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["execution_live_symbols"] == []
    assert payload["approves_live"] is False
    assert payload["approves_canary"] is False
    assert redis.set_calls == []

    paths = gate.default_paths(tmp_path)
    for required in [
        "v2_dynamic_93_by_symbol_edge_attribution.json",
        "v2_public_intel_signal_contribution_status.json",
        "v2_trainer_confidence_calibration_status.json",
        "v2_risk_paper_decision_quality_status.json",
        "v2_strategy_fallback_edge_comparison_status.json",
        "v2_dynamic_93_edge_recompute_after_quality_fixes.json",
        "operator_dashboard_payload.json",
        "GO_NO_GO.md",
    ]:
        assert (paths.public_dir / required).exists(), required
        assert (paths.worklog_dir / required).exists(), required
        assert (paths.operator_runtime_dir / required).exists(), required

    assert (paths.public_dir / "GO_NO_GO.md").read_text().strip() == gate.GO_NO_GO_BLOCKED
    public_intel = json.loads((paths.public_dir / "v2_public_intel_signal_contribution_status.json").read_text())
    assert {row["mode"] for row in public_intel["comparison_modes"]} == {
        "with_public_intel",
        "without_public_intel",
        "defillama_only",
        "news_only",
        "fear_greed_only",
        "mempool_only",
    }
    calibration = json.loads((paths.public_dir / "v2_trainer_confidence_calibration_status.json").read_text())
    assert len(calibration["prediction_overlay_rows"]) == 93
    risk_quality = json.loads((paths.public_dir / "v2_risk_paper_decision_quality_status.json").read_text())
    assert risk_quality["safe_paper_only_guards"]["live_symbols"] == []
