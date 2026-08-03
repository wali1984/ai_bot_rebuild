from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from v2.backend.app.cli.run_paper_shadow_edge_report import build_reports, main
from v2.backend.app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION


def wrap(category: str, redis_key: str, value: dict) -> dict:
    return {"category": category, "redis_key": redis_key, "value": value}


def trusted_prediction(**overrides) -> dict:
    record = {
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "decision_id": "d1",
        "prediction_id": "p1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": "2026-06-13T00:10:00Z",
        "feature_cutoff": "2026-06-13T00:00:00Z",
        "available_at": "2026-06-13T00:00:01Z",
        "generated_at": "2026-06-13T00:10:01Z",
        "input_feature_hash": "hash1",
        "model_version": "model1",
        "policy_version": "policy1",
        "confidence_raw": 0.0,
        "confidence_calibrated": 0.0,
        "confidence_calibration": {"mode": "publisher_proof_hold_no_trade"},
        "mtf_snapshot_id": "mtf1",
        "replay_snapshot_id": "rs1",
        "all_tf_candle_timestamps": [1, 2, 3, 4, 5],
        "paper_only": True,
        "shadow_only": False,
        "routes_to_live": False,
        "live_order_allowed": False,
        "selected_action": "hold",
        "paper_fill_allowed": False,
        "paper_eligible": False,
    }
    record.update(overrides)
    return record


def replay_snapshot() -> dict:
    return {
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "prediction_id": "p1",
        "decision_id": "d1",
        "replay_snapshot_id": "rs1",
        "mtf_snapshot_id": "mtf1",
    }


def mtf_snapshot(**overrides) -> dict:
    candles = {
        "1m": candle(540_000, 599_999),
        "5m": candle(0, 299_999),
        "15m": candle(0, 149_999),
        "1h": candle(0, 89_999),
        "4h": candle(0, 59_999),
    }
    record = {
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "prediction_id": "p1",
        "decision_id": "d1",
        "mtf_snapshot_id": "mtf1",
        "replay_snapshot_id": "rs1",
        "selected_candles": candles,
        "missing_timeframes": [],
        "reject_reasons": [],
    }
    record.update(overrides)
    return record


def candle(open_time: int, close_time: int) -> dict:
    return {
        "candle_open_time": open_time,
        "candle_close_time": close_time,
        "event_time": close_time,
        "available_at": close_time + 1,
        "is_closed": True,
        "source": "binance_rest",
    }


def closed_trade(**overrides) -> dict:
    record = {
        "prediction_id": "p1",
        "decision_id": "d1",
        "replay_snapshot_id": "rs1",
        "mtf_snapshot_id": "mtf1",
        "trade_status": "closed",
        "symbol": "BTCUSDT",
        "side": "long",
        "gross_pnl": 10.0,
        "fees": 1.0,
        "slippage": 2.0,
        "fill_price": 100.0,
        "exit_price": 110.0,
        "fill_price_provenance": "paper_ledger",
        "entry_time": "2026-06-13T00:00:00Z",
        "exit_time": "2026-06-13T00:10:00Z",
    }
    record.update(overrides)
    return record


def write_evidence(tmp_path: Path, *, prediction: dict | None = None, trades: list[dict] | None = None) -> Path:
    run_dir = tmp_path / "evidence"
    run_dir.mkdir()
    rows = {
        "predictions.jsonl": [wrap("predictions", "v2:prediction:BTCUSDT:1m", prediction or trusted_prediction())],
        "replay_snapshots.jsonl": [wrap("replay_snapshots", "v2:replay:snapshots:rs1", replay_snapshot())],
        "mtf_snapshots.jsonl": [wrap("mtf_snapshots", "v2:market:mtf_snapshot:mtf1", mtf_snapshot())],
        "execution_records.jsonl": [wrap("execution_records", "v2:paper:intents", trade) for trade in (trades or [])],
        "masa_ppo.jsonl": [
            wrap(
                "masa_ppo",
                "v2:signals:paper:BTCUSDT:1m",
                {
                    "prediction_id": "p1",
                    "action": "hold",
                    "paper_fill_gate_block_reasons": ["confidence_below_threshold"],
                    "paper_fill_gate_status": "PAPER_SHADOW_GATE_BLOCKED",
                },
            )
        ],
        "config_admin.jsonl": [
            wrap(
                "config_admin",
                "v2:live_gate:state",
                {
                    "live_gate": "blocked_human_only",
                    "order_transport_submit_enabled": False,
                    "live_trading_enabled": False,
                    "places_real_order": False,
                    "exchange_action_taken": False,
                },
            )
        ],
    }
    for name, values in rows.items():
        (run_dir / name).write_text("".join(json.dumps(value) + "\n" for value in values), encoding="utf-8")
    report_dir = run_dir / "report"
    report_dir.mkdir()
    (report_dir / "pipeline_trust_report.json").write_text(json.dumps({"summary": {"critical_failures": 0}}), encoding="utf-8")
    return run_dir


def test_clean_decision_without_closed_trades_is_preliminary(tmp_path: Path) -> None:
    evidence = write_evidence(tmp_path)
    bundle = build_reports(evidence_dir=evidence, min_trusted_decisions=1, min_closed_trades=1)

    assert bundle["edge_report"]["active_decisions_evaluated"] == 1
    assert bundle["edge_report"]["closed_trades_evaluated"] == 0
    assert bundle["edge_report"]["active_out_of_order_candle_count"] == 0
    assert bundle["edge_report"]["metrics"]["net_pnl_after_fees_slippage"] is None
    assert bundle["release_gate"]["sample_size_status"] == "NO-GO"
    assert bundle["release_gate"]["edge_gate_status"] == "NO_CLOSED_TRADE_OUTCOMES"
    assert bundle["release_gate"]["pass2c_verdict"] == "NO-GO"
    assert bundle["edge_report"]["accepted_paper_intents"] == 0
    assert bundle["lifecycle_diagnostics"]["summary"] == {"intent_blocked": 1}
    assert bundle["paper_intent_block_trace"]["distribution"]["LOW_CONFIDENCE_BLOCK"]["count"] == 1
    assert bundle["confidence_block_trace"]["predictions_below_threshold"] == 1
    assert bundle["confidence_block_trace"]["real_model_confidence_count"] == 0
    assert bundle["prediction_producer_inventory"]["current_evidence"]["confidence_source_counts"]["PROOF_DEFAULT"] == 1
    assert bundle["pass2e_release_gate"]["verdict"] == "NO-GO"
    assert bundle["pass2e_release_gate"]["reason"] == "PLACEHOLDER_CONFIDENCE_PERSISTS"


def test_closed_trade_subtracts_fees_and_slippage(tmp_path: Path) -> None:
    evidence = write_evidence(
        tmp_path,
        prediction=trusted_prediction(
            selected_action="long",
            paper_fill_allowed=True,
            paper_eligible=True,
            confidence_raw=0.82,
            confidence_calibrated=0.82,
            confidence_calibration={"mode": "real_model"},
            confidence_source="REAL_MODEL",
            proof_only=False,
            model_consumable=True,
            paper_intent_consumable=True,
            routeability_candidate=True,
        ),
        trades=[closed_trade()],
    )
    bundle = build_reports(evidence_dir=evidence, min_trusted_decisions=1, min_closed_trades=1, profit_factor_threshold=1.0)

    assert bundle["edge_report"]["closed_trades_evaluated"] == 1
    assert bundle["edge_report"]["real_routeability_candidates_evaluated"] == 1
    assert bundle["confidence_block_trace"]["real_model_confidence_count"] == 1
    assert bundle["edge_report"]["metrics"]["net_pnl_after_fees_slippage"] == 7.0
    assert bundle["edge_report"]["metrics"]["expectancy_per_closed_trade"] == 7.0


def test_incomplete_closed_trade_is_not_counted_as_edge(tmp_path: Path) -> None:
    bad_trade = closed_trade(fees=None)
    evidence = write_evidence(
        tmp_path,
        prediction=trusted_prediction(selected_action="long", paper_fill_allowed=True, paper_eligible=True),
        trades=[bad_trade],
    )
    bundle = build_reports(evidence_dir=evidence, min_trusted_decisions=1, min_closed_trades=1)

    assert bundle["edge_report"]["closed_trades_evaluated"] == 0
    assert bundle["edge_report"]["incomplete_closed_trades_excluded"] == 1
    assert bundle["edge_report"]["metrics"]["profit_factor_after_fees_slippage"] is None


def test_live_routable_prediction_is_no_go(tmp_path: Path) -> None:
    evidence = write_evidence(tmp_path, prediction=trusted_prediction(routes_to_live=True))
    bundle = build_reports(evidence_dir=evidence, min_trusted_decisions=1, min_closed_trades=1)

    assert bundle["edge_report"]["active_decisions_evaluated"] == 0
    assert bundle["release_gate"]["sample_size_status"] == "NO-GO"
    assert bundle["edge_report"]["live_prediction_records_excluded"] == 1


def test_cli_writes_required_output_files(tmp_path: Path) -> None:
    evidence = write_evidence(tmp_path)
    out = tmp_path / "out"

    assert main(["--input", str(evidence), "--output-dir", str(out), "--min-trusted-decisions", "1", "--min-closed-trades", "1"]) == 1
    for name in (
        "paper_shadow_edge_report.json",
        "paper_shadow_edge_report.md",
        "paper_shadow_ablation_report.json",
        "paper_shadow_ablation_report.md",
        "paper_shadow_symbol_liquidity_report.json",
        "paper_shadow_trade_sample.jsonl",
        "paper_shadow_closed_trades.jsonl",
        "paper_shadow_open_trades.jsonl",
        "paper_shadow_lifecycle_diagnostics.json",
        "paper_intent_block_trace.json",
        "paper_intent_block_trace.md",
        "confidence_block_trace.json",
        "confidence_block_trace.md",
        "prediction_producer_inventory.json",
        "prediction_producer_inventory.md",
        "pass2b_release_gate.json",
        "pass2b_final_release_gate.json",
        "pass2e_release_gate.json",
    ):
        assert (out / name).exists()
