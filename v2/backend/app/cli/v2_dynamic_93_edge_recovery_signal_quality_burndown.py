"""V2 dynamic 93 edge-recovery and signal-quality burndown gate.

Read-only analyzer for the dynamic 93-symbol paper/shadow runtime. It
attributes by-symbol edge, measures public-intel contribution, calibrates
trainer confidence, audits paper/risk decisions, compares diagnostic fallback
strategies, and recomputes paper edge after conservative quality overlays.

This lane never writes Redis, never calls exchange endpoints, and never
changes live/canary state.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from v2.backend.app.cli import (
    v2_dynamic_93_symbol_runtime_burn_in_edge_and_website_sync as base_gate,
)


THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
LANE_ID = "v2_dynamic_93_edge_recovery_and_signal_quality_burndown"

GO_NO_GO_READY = "V2_DYNAMIC_93_EDGE_RECOVERY_AND_SIGNAL_QUALITY_BURNDOWN_READY"
GO_NO_GO_BLOCKED = "V2_DYNAMIC_93_EDGE_RECOVERY_AND_SIGNAL_QUALITY_BURNDOWN_BLOCKED"

TARGET_DYNAMIC_SYMBOL_COUNT = 93
TIMEFRAME = "1m"
PRIMARY_OUTCOME_WINDOW = "5m"
MIN_BY_SYMBOL_OUTCOME_SAMPLE = 5
MIN_RECOMPUTE_OUTCOME_SAMPLE = 30
MIN_VALIDATION_ROWS = 100
MIN_EXPECTED_AFTER_COST_BPS = 8.0
MIN_CONFIDENCE_AFTER_PENALTY = 0.70
MAX_SYMBOL_SELECTION_SHARE = 0.15
MAX_TOP5_SELECTION_SHARE = 0.50


@dataclass(frozen=True)
class PacketPaths:
    worklog_dir: Path
    public_dir: Path
    operator_runtime_dir: Path


def default_paths(repo_root: Path = REPO_ROOT) -> PacketPaths:
    return PacketPaths(
        worklog_dir=repo_root / "claude_worklog" / "final_readiness" / LANE_ID / "latest",
        public_dir=repo_root / "v2" / "frontend" / "public" / LANE_ID / "latest",
        operator_runtime_dir=repo_root
        / "v2"
        / "frontend"
        / "public"
        / "operator_runtime"
        / LANE_ID
        / "latest",
    )


def _now():
    return base_gate._now()


def _generated_block(now: Any) -> dict[str, str]:
    return base_gate._generated_block(now)


def _safety_block() -> dict[str, Any]:
    safety = base_gate._safety_block()
    safety.update(
        {
            "quality_overlay_applies_to_live": False,
            "quality_overlay_applies_to_canary": False,
            "paper_shadow_only": True,
            "execution_mutation_enabled": False,
        }
    )
    return safety


def _write_json(path: Path, payload: Any) -> None:
    base_gate._write_json(path, payload)


def _write_text(path: Path, text: str) -> None:
    base_gate._write_text(path, text)


def _read_json(path: Path) -> Any | None:
    return base_gate._read_json(path)


def _connect_redis() -> Any | None:  # pragma: no cover - runtime path
    return base_gate._connect_redis()


def _redis_get_json(redis_client: Any | None, key: str) -> Any | None:
    return base_gate._redis_get_json(redis_client, key)


def _number(value: Any) -> float | None:
    return base_gate._number(value)


def _as_symbol_list(value: Any) -> list[str]:
    return base_gate._as_symbol_list(value)


def _freshness(payload: Any, *, now: Any, limit_seconds: int) -> dict[str, Any]:
    return base_gate._freshness(payload, now=now, limit_seconds=limit_seconds)


def _distribution(values: Iterable[Any]) -> dict[str, Any]:
    return base_gate._distribution(values)


def _load_replay_rows(path: Path, symbols: set[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return base_gate._load_replay_rows(path, symbols)


def _mean(values: Iterable[float]) -> float | None:
    vals = [float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(float(v))]
    return statistics.fmean(vals) if vals else None


def _sum(values: Iterable[float]) -> float | None:
    vals = [float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(float(v))]
    return sum(vals) if vals else None


def _ci_lower(values: Iterable[float]) -> float | None:
    vals = [float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(float(v))]
    if len(vals) < 2:
        return None
    return statistics.fmean(vals) - 1.96 * (statistics.stdev(vals) / math.sqrt(len(vals)))


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _counter_dict(counter: Counter[str], limit: int | None = None) -> dict[str, int]:
    items = counter.most_common(limit) if limit else counter.items()
    return {str(k): int(v) for k, v in items}


def _load_public_payloads(repo_root: Path) -> dict[str, Any]:
    public = repo_root / "v2/frontend/public"
    paths = {
        "symbol_universe": public / "operator_runtime/symbol_universe/latest/symbol_universe_status.json",
        "public_intel": public
        / "operator_runtime/v2_public_intel_free_tier/latest/v2_public_intel_free_tier_status.json",
        "trainer_live_loop": public
        / "operator_runtime/v2_trainer_training_live_loop/latest/v2_trainer_training_live_loop_status.json",
        "post_hoc_replay": public
        / "v2_post_hoc_replay_outcome_miner/latest/post_hoc_replay_outcome_status.json",
        "post_hoc_edge_metrics": public
        / "v2_post_hoc_replay_outcome_miner/latest/edge_metrics_summary.json",
        "paper_worker": public
        / "operator_runtime/v2_paper_execution_worker/latest/v2_paper_execution_worker_status.json",
        "risk_decisions": public / "operator_runtime/paper_online/latest/current_risk_decisions.json",
        "previous_dynamic_93": public
        / "v2_dynamic_93_symbol_runtime_burn_in_edge_and_website_sync/latest/operator_dashboard_payload.json",
    }
    return {name: {"path": str(path), "payload": _read_json(path)} for name, path in paths.items()}


def _resolve_runtime_symbols(repo_root: Path) -> tuple[list[str], dict[str, Any]]:
    return base_gate._resolve_runtime_symbols(repo_root)


def _replay_bundle_path(repo_root: Path) -> Path:
    return repo_root / "v2/frontend/public/v2_post_hoc_replay_outcome_miner/latest/replay_outcome_bundles.jsonl"


def _outcome(row: Mapping[str, Any], window: str = PRIMARY_OUTCOME_WINDOW) -> Mapping[str, Any]:
    future = row.get("future_outcomes") if isinstance(row.get("future_outcomes"), Mapping) else {}
    value = future.get(window) if isinstance(future, Mapping) else {}
    return value if isinstance(value, Mapping) else {}


def _after_cost(row: Mapping[str, Any]) -> float | None:
    return _number(_first_present(_outcome(row).get("after_cost_return_bps"), row.get("outcome_after_cost")))


def _drawdown(row: Mapping[str, Any]) -> float | None:
    return _number(_first_present(_outcome(row).get("drawdown_bps"), _outcome(row).get("max_adverse_bps")))


def _trainer_output(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("trainer_output")
    return value if isinstance(value, Mapping) else {}


def _risk_decision(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("risk_decision")
    return value if isinstance(value, Mapping) else {}


def _paper_gate(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("paper_gate_decision")
    return value if isinstance(value, Mapping) else {}


def _paper_intent(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("paper_intent")
    return value if isinstance(value, Mapping) else {}


def _paper_fill_allowed(row: Mapping[str, Any]) -> bool:
    if row.get("paper_fill_allowed") is not None:
        return bool(row.get("paper_fill_allowed"))
    gate = _paper_gate(row)
    if gate.get("paper_fill_allowed") is not None:
        return bool(gate.get("paper_fill_allowed"))
    return False


def _trade_intended(row: Mapping[str, Any]) -> bool:
    intent = _paper_intent(row)
    trainer = _trainer_output(row)
    if intent:
        decision = str(intent.get("decision") or "").upper()
        if decision and decision not in {"NOOP", "HOLD"}:
            return True
    action = str(trainer.get("selected_action") or row.get("side") or "").lower()
    return action not in {"", "hold", "none"}


def _confidence(row: Mapping[str, Any]) -> float | None:
    trainer = _trainer_output(row)
    return _number(
        _first_present(
            trainer.get("confidence_calibrated"),
            row.get("confidence_calibrated"),
            row.get("input_prediction_confidence_calibrated"),
        )
    )


def _expected_after_cost(row: Mapping[str, Any]) -> float | None:
    trainer = _trainer_output(row)
    return _number(
        _first_present(
            trainer.get("expected_move_after_cost_bps"),
            row.get("expected_move_after_cost_bps"),
            row.get("expected_move_after_costs_bps"),
        )
    )


def _risk_block_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    for source in (
        row.get("paper_fill_gate_block_reasons"),
        _paper_gate(row).get("paper_fill_gate_block_reasons"),
        _trainer_output(row).get("paper_fill_gate_block_reasons"),
    ):
        if isinstance(source, list):
            reasons.extend(str(item) for item in source if str(item))
    risk = _risk_decision(row)
    if risk.get("pre_trade_allowed") is False:
        reasons.append("PRE_TRADE_GATE_BLOCKED")
        if risk.get("pre_trade_reason"):
            reasons.append(str(risk.get("pre_trade_reason")))
    if risk.get("fee_gate_allowed") is False:
        reasons.append("FEE_GATE_BLOCKED")
        if risk.get("fee_gate_reason"):
            reasons.append(str(risk.get("fee_gate_reason")))
    if risk.get("churn_blocked") is True:
        reasons.append("CHURN_BLOCKED")
        if risk.get("churn_reason"):
            reasons.append(str(risk.get("churn_reason")))
    if _paper_fill_allowed(row) is False and not reasons:
        lineage = row.get("paper_fill_gate_block_reasons_lineage") or _paper_gate(row).get(
            "paper_fill_gate_block_reasons_lineage"
        )
        if isinstance(lineage, Mapping) and lineage.get("state") == "MISSING_SOURCE":
            reasons.append("PAPER_FILL_HELD_REASON_LINEAGE_MISSING")
        elif _trade_intended(row):
            reasons.append("PAPER_FILL_HELD_SHADOW_ONLY")
    return sorted(set(reasons))


def _decision_outcome(row: Mapping[str, Any]) -> str:
    ac = _after_cost(row)
    allowed = _paper_fill_allowed(row)
    if ac is None:
        return "AWAITING_OUTCOME"
    if allowed and ac > 0:
        return "ALLOWED_WINNER"
    if allowed and ac <= 0:
        return "ALLOWED_LOSER"
    if not allowed and ac > 0:
        return "MISSED_WINNER"
    return "CORRECT_NO_TRADE"


def _prediction_snapshot(redis_client: Any | None, symbol: str) -> Mapping[str, Any]:
    value = _redis_get_json(redis_client, f"v2:prediction:{symbol}:{TIMEFRAME}")
    return value if isinstance(value, Mapping) else {}


def _feature_snapshot(redis_client: Any | None, symbol: str) -> Mapping[str, Any]:
    value = _redis_get_json(redis_client, f"v2:features:latest:{symbol}:{TIMEFRAME}")
    return value if isinstance(value, Mapping) else {}


def _features(redis_client: Any | None, symbol: str) -> Mapping[str, Any]:
    payload = _feature_snapshot(redis_client, symbol)
    value = payload.get("features")
    return value if isinstance(value, Mapping) else {}


def _provider_scores(redis_client: Any | None, symbol: str) -> dict[str, Any]:
    public_intel = _redis_get_json(redis_client, f"v2:altdata:public_intel:symbol:{symbol}")
    symbol_score = _redis_get_json(redis_client, f"v2:altdata:symbol_score:{symbol}")
    pi = public_intel if isinstance(public_intel, Mapping) else {}
    score = symbol_score if isinstance(symbol_score, Mapping) else {}
    return {
        "public_intel_score": _number(
            _first_present(pi.get("public_intel_score"), score.get("public_intel_score"))
        ),
        "defillama_liquidity_score": _number(
            _first_present(pi.get("defillama_liquidity_score"), score.get("defillama_liquidity_score"))
        ),
        "defillama_tvl_momentum_score": _number(
            _first_present(
                pi.get("defillama_tvl_momentum_score"), score.get("defillama_tvl_momentum_score")
            )
        ),
        "news_attention_score": _number(
            _first_present(pi.get("news_attention_score"), score.get("news_attention_score"))
        ),
        "news_sentiment_score": _number(
            _first_present(pi.get("news_sentiment_score"), score.get("news_sentiment_score"))
        ),
        "fear_greed_score": _number(_first_present(pi.get("fear_greed_score"), score.get("fear_greed_score"))),
        "btc_mempool_pressure_score": _number(
            _first_present(pi.get("btc_mempool_pressure_score"), score.get("btc_mempool_pressure_score"))
        ),
        "altdata_symbol_score": _number(score.get("altdata_symbol_score")),
        "provider_presence": dict(score.get("input_presence") or {}) if isinstance(score.get("input_presence"), Mapping) else {},
        "missing_provider_flags": list(score.get("missing_provider_flags") or []) if isinstance(score.get("missing_provider_flags"), list) else [],
    }


def _confidence_bucket(value: float | None) -> str:
    if value is None:
        return "missing"
    if value < 0.4:
        return "0.0_to_0.4"
    if value < 0.55:
        return "0.4_to_0.55"
    if value < 0.65:
        return "0.55_to_0.65"
    if value < 0.75:
        return "0.65_to_0.75"
    return "0.75_to_1.0"


def build_by_symbol_edge_attribution(
    *,
    symbols: list[str],
    replay_rows: list[dict[str, Any]],
    redis_client: Any | None,
    now: Any,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in symbols}
    for row in replay_rows:
        symbol = str(row.get("symbol") or "").upper()
        if symbol in grouped:
            grouped[symbol].append(row)

    total_bundle_count = sum(len(rows) for rows in grouped.values())
    rows_out: list[dict[str, Any]] = []
    classification_counts: Counter[str] = Counter()
    outcome_counts: Counter[str] = Counter()

    for symbol in symbols:
        symbol_rows = grouped[symbol]
        after_values = [value for value in (_after_cost(row) for row in symbol_rows) if value is not None]
        drawdowns = [value for value in (_drawdown(row) for row in symbol_rows) if value is not None]
        confidences = [_confidence(row) for row in symbol_rows]
        expected_values = [_expected_after_cost(row) for row in symbol_rows]
        label_counts = Counter(str(row.get("label") or "unknown") for row in symbol_rows)
        risk_reasons = Counter(reason for row in symbol_rows for reason in _risk_block_reasons(row))
        decision_counts = Counter(_decision_outcome(row) for row in symbol_rows)
        outcome_counts.update(decision_counts)
        feature = _feature_snapshot(redis_client, symbol)
        prediction = _prediction_snapshot(redis_client, symbol)
        provider = _provider_scores(redis_client, symbol)
        feature_freshness = _freshness(feature, now=now, limit_seconds=15 * 60)
        prediction_freshness = _freshness(prediction, now=now, limit_seconds=30 * 60)

        sample_count = len(after_values)
        mean_after = _mean(after_values)
        bundle_share = (len(symbol_rows) / total_bundle_count) if total_bundle_count else 0.0
        risk_block_rate = _rate(sum(risk_reasons.values()), len(symbol_rows))
        if feature_freshness["state"] != "FRESH" or prediction_freshness["state"] != "FRESH":
            classification = "DATA_STALE"
        elif sample_count < MIN_BY_SYMBOL_OUTCOME_SAMPLE:
            classification = "INSUFFICIENT_SAMPLE"
        elif bundle_share >= MAX_SYMBOL_SELECTION_SHARE:
            classification = "OVERCONCENTRATED"
        elif risk_block_rate is not None and risk_block_rate >= 0.50:
            classification = "RISK_BLOCK_DOMINANT"
        elif mean_after is not None and mean_after > 0:
            classification = "EDGE_POSITIVE_CANDIDATE"
        else:
            classification = "EDGE_NEGATIVE_BLOCK"
        classification_counts[classification] += 1

        rows_out.append(
            {
                "symbol": symbol,
                "classification": classification,
                "paper_pnl_after_cost_bps_sum": _sum(after_values),
                "after_cost_expectancy_bps": mean_after,
                "after_cost_ci_lower_bps": _ci_lower(after_values),
                "trade_intention_count": sum(1 for row in symbol_rows if _trade_intended(row)),
                "paper_trade_allowed_count": sum(1 for row in symbol_rows if _paper_fill_allowed(row)),
                "bundle_count": len(symbol_rows),
                "outcome_sample_count": sample_count,
                "false_positives": label_counts.get("false_positive", 0),
                "false_negatives": label_counts.get("false_negative", 0),
                "no_trade_correctness": label_counts.get("correct_no_trade", 0),
                "label_counts": dict(label_counts),
                "feature_freshness": feature_freshness,
                "prediction_freshness": prediction_freshness,
                "prediction_confidence_distribution": _distribution(confidences),
                "expected_move_after_cost_distribution_bps": _distribution(expected_values),
                "current_prediction_confidence": _number(prediction.get("confidence_calibrated")),
                "current_prediction_expected_after_cost_bps": _number(
                    prediction.get("expected_move_after_cost_bps")
                ),
                "current_prediction_action": prediction.get("selected_action"),
                "provider_score": provider,
                "risk_block_rate": risk_block_rate,
                "risk_block_reason_counts": _counter_dict(risk_reasons, 12),
                "decision_outcome_counts": dict(decision_counts),
                "decision_outcome": decision_counts.most_common(1)[0][0] if decision_counts else "NO_REPLAY_ROWS",
                "max_drawdown_bps": max(drawdowns) if drawdowns else None,
                "bundle_share": round(bundle_share, 6),
            }
        )

    positive_rows = [row for row in rows_out if row["after_cost_expectancy_bps"] is not None and row["after_cost_expectancy_bps"] > 0]
    rows_sorted = sorted(
        positive_rows,
        key=lambda row: (
            row["after_cost_expectancy_bps"] is None,
            -(row["after_cost_expectancy_bps"] or -1e9),
        ),
    )
    negative_sorted = sorted(
        rows_out,
        key=lambda row: (
            row["after_cost_expectancy_bps"] is None,
            row["after_cost_expectancy_bps"] if row["after_cost_expectancy_bps"] is not None else 1e9,
        ),
    )
    return {
        "schema_version": "v2_dynamic_93_by_symbol_edge_attribution_v1",
        **_generated_block(now),
        **_safety_block(),
        "symbol_count": len(symbols),
        "replay_bundle_count": total_bundle_count,
        "primary_outcome_window": PRIMARY_OUTCOME_WINDOW,
        "classification_counts": dict(classification_counts),
        "decision_outcome_counts": dict(outcome_counts),
        "top_positive_symbols": rows_sorted[:12],
        "top_negative_symbols": negative_sorted[:12],
        "per_symbol": rows_out,
    }


def _score_for_mode(provider: Mapping[str, Any], mode: str) -> float | None:
    if mode == "with_public_intel":
        return _number(provider.get("public_intel_score"))
    if mode == "without_public_intel":
        base_score = _number(provider.get("altdata_symbol_score"))
        public = _number(provider.get("public_intel_score")) or 0.0
        return None if base_score is None else max(0.0, base_score - 0.25 * public)
    if mode == "defillama_only":
        parts = [
            _number(provider.get("defillama_liquidity_score")),
            _number(provider.get("defillama_tvl_momentum_score")),
        ]
        return _mean([p for p in parts if p is not None])
    if mode == "news_only":
        parts = [_number(provider.get("news_attention_score")), _number(provider.get("news_sentiment_score"))]
        return _mean([p for p in parts if p is not None])
    if mode == "fear_greed_only":
        return _number(provider.get("fear_greed_score"))
    if mode == "mempool_only":
        return _number(provider.get("btc_mempool_pressure_score"))
    return None


def _filled_rows_for_symbols(replay_rows: list[dict[str, Any]], symbols: set[str]) -> list[dict[str, Any]]:
    return [row for row in replay_rows if str(row.get("symbol") or "").upper() in symbols and _after_cost(row) is not None]


def build_public_intel_signal_contribution_status(
    *,
    symbols: list[str],
    replay_rows: list[dict[str, Any]],
    redis_client: Any | None,
    public_payloads: Mapping[str, Any],
    now: Any,
) -> dict[str, Any]:
    provider_by_symbol = {symbol: _provider_scores(redis_client, symbol) for symbol in symbols}
    modes = [
        "with_public_intel",
        "without_public_intel",
        "defillama_only",
        "news_only",
        "fear_greed_only",
        "mempool_only",
    ]
    mode_rows: list[dict[str, Any]] = []
    for mode in modes:
        scored = [
            {
                "symbol": symbol,
                "score": _score_for_mode(provider_by_symbol[symbol], mode),
                "provider_score": provider_by_symbol[symbol],
            }
            for symbol in symbols
        ]
        scored = [row for row in scored if row["score"] is not None]
        scored.sort(key=lambda row: float(row["score"]), reverse=True)
        selected_symbols = {row["symbol"] for row in scored[: min(20, len(scored))]}
        filled = _filled_rows_for_symbols(replay_rows, selected_symbols)
        after_values = [value for value in (_after_cost(row) for row in filled) if value is not None]
        labels = Counter(str(row.get("label") or "unknown") for row in filled)
        risk_blocked = sum(1 for row in filled if _risk_block_reasons(row))
        mean_after = _mean(after_values)
        ci_lower = _ci_lower(after_values)
        sample_ok = len(after_values) >= MIN_RECOMPUTE_OUTCOME_SAMPLE
        proof_passed = bool(sample_ok and mean_after is not None and mean_after > 0 and ci_lower is not None and ci_lower > 0)
        mode_rows.append(
            {
                "mode": mode,
                "scored_symbol_count": len(scored),
                "selected_symbol_count": len(selected_symbols),
                "selected_symbols": sorted(selected_symbols),
                "top_scored_symbols": scored[:10],
                "outcome_sample_count": len(after_values),
                "after_cost_expectancy_bps": mean_after,
                "after_cost_ci_lower_bps": ci_lower,
                "label_counts": dict(labels),
                "false_positive_count": labels.get("false_positive", 0),
                "false_negative_count": labels.get("false_negative", 0),
                "correct_no_trade_count": labels.get("correct_no_trade", 0),
                "risk_block_rate": _rate(risk_blocked, len(filled)),
                "after_cost_proof_state": (
                    "PAPER_EDGE_PROOF_PASSED_SHADOW_ONLY"
                    if proof_passed
                    else "INSUFFICIENT_OUTCOME_SAMPLE"
                    if not sample_ok
                    else "PAPER_EDGE_NOT_PROVEN_AFTER_COST"
                ),
                "edge_claimed": False,
            }
        )
    pi_payload = public_payloads["public_intel"]["payload"] or {}
    return {
        "schema_version": "v2_public_intel_signal_contribution_status_v1",
        **_generated_block(now),
        **_safety_block(),
        "public_intel_payload_path": public_payloads["public_intel"]["path"],
        "public_intel_go_no_go": pi_payload.get("go_no_go") if isinstance(pi_payload, Mapping) else None,
        "public_intel_symbol_count": pi_payload.get("symbol_count") if isinstance(pi_payload, Mapping) else None,
        "successful_symbol_count": pi_payload.get("successful_symbol_count") if isinstance(pi_payload, Mapping) else None,
        "comparison_modes": mode_rows,
        "edge_claimed": False,
        "edge_claim_policy": "No public-intel mode may claim edge unless after-cost expectancy and lower CI pass on sufficient paper outcomes.",
    }


def build_trainer_confidence_calibration_status(
    *,
    symbols: list[str],
    replay_rows: list[dict[str, Any]],
    by_symbol: Mapping[str, Any],
    redis_client: Any | None,
    public_payloads: Mapping[str, Any],
    now: Any,
) -> dict[str, Any]:
    buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "count": 0,
            "winner_count": 0,
            "loser_count": 0,
            "after_cost_values": [],
            "expected_values": [],
            "absolute_errors": [],
        }
    )
    high_conf_losers: list[dict[str, Any]] = []
    low_conf_winners: list[dict[str, Any]] = []
    null_confidence_cases = 0
    null_expected_cases = 0
    symbol_high_conf_loss_counts: Counter[str] = Counter()
    symbol_outcome_counts: Counter[str] = Counter()

    for row in replay_rows:
        ac = _after_cost(row)
        if ac is None:
            continue
        symbol = str(row.get("symbol") or "").upper()
        conf = _confidence(row)
        expected = _expected_after_cost(row)
        bucket = _confidence_bucket(conf)
        item = buckets[bucket]
        item["count"] += 1
        item["after_cost_values"].append(ac)
        if expected is not None:
            item["expected_values"].append(expected)
            item["absolute_errors"].append(abs(expected - ac))
        else:
            null_expected_cases += 1
        if conf is None:
            null_confidence_cases += 1
        if ac > 0:
            item["winner_count"] += 1
        else:
            item["loser_count"] += 1
        symbol_outcome_counts[symbol] += 1
        if conf is not None and conf >= 0.65 and ac <= 0:
            symbol_high_conf_loss_counts[symbol] += 1
            high_conf_losers.append(
                {
                    "symbol": symbol,
                    "confidence_calibrated": conf,
                    "expected_move_after_cost_bps": expected,
                    "realized_after_cost_bps": ac,
                    "label": row.get("label"),
                    "prediction_id": row.get("prediction_id"),
                }
            )
        if conf is not None and conf < 0.55 and ac > 0:
            low_conf_winners.append(
                {
                    "symbol": symbol,
                    "confidence_calibrated": conf,
                    "expected_move_after_cost_bps": expected,
                    "realized_after_cost_bps": ac,
                    "label": row.get("label"),
                    "prediction_id": row.get("prediction_id"),
                }
            )

    bucket_rows: list[dict[str, Any]] = []
    calibration_errors: list[float] = []
    for bucket, item in sorted(buckets.items()):
        mean_expected = _mean(item["expected_values"])
        mean_realized = _mean(item["after_cost_values"])
        bucket_error = None
        if mean_expected is not None and mean_realized is not None:
            bucket_error = abs(mean_expected - mean_realized)
            calibration_errors.append(bucket_error)
        bucket_rows.append(
            {
                "bucket": bucket,
                "count": item["count"],
                "winner_count": item["winner_count"],
                "loser_count": item["loser_count"],
                "win_rate": _rate(item["winner_count"], item["count"]),
                "mean_expected_move_after_cost_bps": mean_expected,
                "mean_realized_after_cost_bps": mean_realized,
                "bucket_calibration_error_bps": bucket_error,
                "mean_absolute_error_bps": _mean(item["absolute_errors"]),
            }
        )

    negative_symbols = {
        row["symbol"]
        for row in (by_symbol.get("per_symbol") or [])
        if isinstance(row, Mapping) and row.get("classification") == "EDGE_NEGATIVE_BLOCK"
    }
    prediction_overlay_rows: list[dict[str, Any]] = []
    for symbol in symbols:
        prediction = _prediction_snapshot(redis_client, symbol)
        conf = _number(prediction.get("confidence_calibrated"))
        expected = _number(prediction.get("expected_move_after_cost_bps"))
        high_conf_loss_rate = _rate(symbol_high_conf_loss_counts[symbol], symbol_outcome_counts[symbol])
        penalty = 0.0
        penalty_reasons: list[str] = []
        if high_conf_loss_rate is not None and high_conf_loss_rate >= 0.50:
            penalty += 0.10
            penalty_reasons.append("HIGH_CONFIDENCE_LOSER_RATE")
        if symbol in negative_symbols:
            penalty += 0.05
            penalty_reasons.append("NEGATIVE_BY_SYMBOL_EXPECTANCY")
        adjusted_conf = None if conf is None else max(0.0, conf - penalty)
        eligible = (
            expected is not None
            and expected >= MIN_EXPECTED_AFTER_COST_BPS
            and adjusted_conf is not None
            and adjusted_conf >= MIN_CONFIDENCE_AFTER_PENALTY
            and symbol not in negative_symbols
        )
        prediction_overlay_rows.append(
            {
                "symbol": symbol,
                "current_confidence_calibrated": conf,
                "confidence_calibration_penalty": round(penalty, 6),
                "adjusted_confidence_calibrated": adjusted_conf,
                "expected_move_after_cost_bps": expected,
                "high_confidence_loser_rate": high_conf_loss_rate,
                "paper_shadow_quality_eligible": eligible,
                "penalty_reasons": penalty_reasons,
            }
        )

    trainer_payload = public_payloads["trainer_live_loop"]["payload"] or {}
    return {
        "schema_version": "v2_trainer_confidence_calibration_status_v1",
        **_generated_block(now),
        **_safety_block(),
        "trainer_classification": trainer_payload.get("classification") if isinstance(trainer_payload, Mapping) else None,
        "trainer_row_count": trainer_payload.get("row_count") if isinstance(trainer_payload, Mapping) else None,
        "trainer_validation_rows": trainer_payload.get("validation_rows") if isinstance(trainer_payload, Mapping) else None,
        "outcome_sample_count": sum(row["count"] for row in bucket_rows),
        "confidence_bucket_vs_outcome": bucket_rows,
        "expected_move_after_cost_vs_realized": {
            "mean_bucket_calibration_error_bps": _mean(calibration_errors),
            "null_expected_move_after_cost_cases": null_expected_cases,
        },
        "high_confidence_losers": sorted(
            high_conf_losers,
            key=lambda row: abs(float(row["realized_after_cost_bps"])),
            reverse=True,
        )[:50],
        "low_confidence_winners": sorted(
            low_conf_winners,
            key=lambda row: float(row["realized_after_cost_bps"]),
            reverse=True,
        )[:50],
        "null_confidence_cases": null_confidence_cases,
        "calibration_error_bps": _mean(calibration_errors),
        "paper_shadow_fixes": {
            "downrank_overconfident_losers": True,
            "require_minimum_expected_edge_after_cost_bps": MIN_EXPECTED_AFTER_COST_BPS,
            "confidence_calibration_penalty_enabled": True,
            "min_confidence_after_penalty": MIN_CONFIDENCE_AFTER_PENALTY,
            "exposes_calibration_metrics_in_prediction_overlay": True,
            "applies_to_live_or_canary": False,
        },
        "prediction_overlay_rows": prediction_overlay_rows,
    }


def _risk_reason_category(reason: str) -> str:
    upper = reason.upper()
    if "FEE" in upper:
        return "fee"
    if "CHURN" in upper or "COOLDOWN" in upper:
        return "churn"
    if "SPREAD" in upper:
        return "spread"
    if "SLIPPAGE" in upper:
        return "slippage"
    if "STALE" in upper or "FRESHNESS" in upper:
        return "stale_feature"
    if "CONCENTR" in upper:
        return "concentration"
    if "PRE_TRADE" in upper or "RISK" in upper:
        return "risk"
    if "LIVE_GATE" in upper:
        return "live_gate"
    return "other"


def build_risk_paper_decision_quality_status(
    *,
    symbols: list[str],
    replay_rows: list[dict[str, Any]],
    by_symbol: Mapping[str, Any],
    public_payloads: Mapping[str, Any],
    now: Any,
) -> dict[str, Any]:
    reason_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    missed_winners: list[dict[str, Any]] = []
    allowed_losers: list[dict[str, Any]] = []
    no_trade_correct = 0
    filled = 0
    for row in replay_rows:
        ac = _after_cost(row)
        reasons = _risk_block_reasons(row)
        for reason in reasons:
            reason_counts[reason] += 1
            category_counts[_risk_reason_category(reason)] += 1
        if ac is None:
            continue
        filled += 1
        symbol = str(row.get("symbol") or "").upper()
        allowed = _paper_fill_allowed(row)
        expected = _expected_after_cost(row)
        confidence = _confidence(row)
        if not allowed and ac > 0:
            missed_winners.append(
                {
                    "symbol": symbol,
                    "realized_after_cost_bps": ac,
                    "expected_move_after_cost_bps": expected,
                    "confidence_calibrated": confidence,
                    "block_reasons": reasons,
                    "label": row.get("label"),
                }
            )
        elif allowed and ac <= 0:
            allowed_losers.append(
                {
                    "symbol": symbol,
                    "realized_after_cost_bps": ac,
                    "expected_move_after_cost_bps": expected,
                    "confidence_calibrated": confidence,
                    "block_reasons": reasons,
                    "label": row.get("label"),
                }
            )
        elif not allowed and ac <= 0:
            no_trade_correct += 1

    negative_symbols = [
        row["symbol"]
        for row in (by_symbol.get("per_symbol") or [])
        if isinstance(row, Mapping) and row.get("classification") == "EDGE_NEGATIVE_BLOCK"
    ]
    bundle_counts = sorted(
        [
            int(row.get("bundle_count") or 0)
            for row in (by_symbol.get("per_symbol") or [])
            if isinstance(row, Mapping)
        ],
        reverse=True,
    )
    total_bundles = sum(bundle_counts)
    risk_payload = public_payloads["risk_decisions"]["payload"] or {}
    paper_payload = public_payloads["paper_worker"]["payload"] or {}
    return {
        "schema_version": "v2_risk_paper_decision_quality_status_v1",
        **_generated_block(now),
        **_safety_block(),
        "outcome_sample_count": filled,
        "risk_block_reason_counts": _counter_dict(reason_counts, 80),
        "risk_block_category_counts": dict(category_counts),
        "fee_block_count": category_counts.get("fee", 0),
        "churn_block_count": category_counts.get("churn", 0),
        "spread_block_count": category_counts.get("spread", 0),
        "slippage_block_count": category_counts.get("slippage", 0),
        "stale_feature_block_count": category_counts.get("stale_feature", 0),
        "concentration": {
            "bundle_count_total": total_bundles,
            "top_symbol_bundle_count": bundle_counts[0] if bundle_counts else 0,
            "top_symbol_bundle_share": round(bundle_counts[0] / total_bundles, 6) if total_bundles else None,
            "top5_symbol_bundle_share": round(sum(bundle_counts[:5]) / total_bundles, 6) if total_bundles else None,
        },
        "missed_winners": sorted(missed_winners, key=lambda row: row["realized_after_cost_bps"], reverse=True)[:50],
        "allowed_losers": sorted(allowed_losers, key=lambda row: row["realized_after_cost_bps"])[:50],
        "no_trade_correct_count": no_trade_correct,
        "safe_paper_only_guards": {
            "block_or_downrank_negative_expectancy_symbols": True,
            "negative_expectancy_symbol_blocklist": negative_symbols,
            "diversify_paper_candidate_selection": True,
            "max_symbol_selection_share": MAX_SYMBOL_SELECTION_SHARE,
            "max_top5_selection_share": MAX_TOP5_SELECTION_SHARE,
            "preserve_live_gate": "blocked_human_only",
            "live_symbols": [],
            "execution_live_symbols": [],
            "applies_to_live_or_canary": False,
        },
        "current_risk_payload_path": public_payloads["risk_decisions"]["path"],
        "current_risk_decision_count": len(risk_payload.get("decisions") or []) if isinstance(risk_payload, Mapping) else 0,
        "paper_worker_payload_path": public_payloads["paper_worker"]["path"],
        "paper_worker_denials_breakdown": paper_payload.get("denials_breakdown") if isinstance(paper_payload, Mapping) else None,
    }


def _feature_number(features: Mapping[str, Any], key: str) -> float | None:
    return _number(features.get(key))


def _strategy_action(strategy: str, features: Mapping[str, Any]) -> str:
    ret = _feature_number(features, "ret_pct") or 0.0
    htf_ret = _feature_number(features, "htf_ret_pct") or 0.0
    ema12 = _feature_number(features, "ema_12")
    ema26 = _feature_number(features, "ema_26")
    rsi = _feature_number(features, "rsi_14")
    htf_rsi = _feature_number(features, "htf_rsi_14")
    macd_hist = _feature_number(features, "macd_hist") or 0.0
    range_pct = _feature_number(features, "range_pct") or 0.0
    funding = _feature_number(features, "funding_rate") or 0.0
    oi_change = _feature_number(features, "oi_change_pct") or 0.0
    liq_bps = _feature_number(features, "last_liq_bps_24h") or 0.0
    imbalance = _feature_number(features, "depth_imbalance") or 0.0
    if strategy == "trend":
        if ema12 is not None and ema26 is not None and ema12 > ema26 and htf_ret >= 0:
            return "long"
        if ema12 is not None and ema26 is not None and ema12 < ema26 and htf_ret <= 0:
            return "short"
    if strategy == "mean_reversion":
        if rsi is not None and rsi < 35:
            return "long"
        if rsi is not None and rsi > 65:
            return "short"
    if strategy == "breakout":
        if range_pct > 0.20 and ret > 0:
            return "long"
        if range_pct > 0.20 and ret < 0:
            return "short"
    if strategy == "momentum":
        if ret > 0 and macd_hist > 0:
            return "long"
        if ret < 0 and macd_hist < 0:
            return "short"
    if strategy == "funding_oi_divergence":
        if funding < 0 and oi_change > 0:
            return "long"
        if funding > 0 and oi_change > 0:
            return "short"
    if strategy == "liquidation_cascade":
        if liq_bps > 10 and ret < 0:
            return "short"
        if liq_bps > 10 and ret > 0:
            return "long"
    if strategy == "orderbook_imbalance":
        if imbalance > 0.15:
            return "long"
        if imbalance < -0.15:
            return "short"
    if strategy == "ta_confirmation":
        if ema12 is not None and ema26 is not None and rsi is not None and htf_rsi is not None:
            if ema12 > ema26 and 45 <= rsi <= 70 and htf_rsi >= 40 and macd_hist > 0:
                return "long"
            if ema12 < ema26 and 30 <= rsi <= 55 and htf_rsi <= 60 and macd_hist < 0:
                return "short"
    return "hold"


def build_strategy_fallback_edge_comparison_status(
    *,
    symbols: list[str],
    replay_rows: list[dict[str, Any]],
    redis_client: Any | None,
    now: Any,
) -> dict[str, Any]:
    features_by_symbol = {symbol: _features(redis_client, symbol) for symbol in symbols}
    strategies = [
        "trainer",
        "trend",
        "mean_reversion",
        "breakout",
        "momentum",
        "funding_oi_divergence",
        "liquidation_cascade",
        "orderbook_imbalance",
        "ta_confirmation",
        "no_trade_preservation",
    ]
    rows_out: list[dict[str, Any]] = []
    filled_rows = [row for row in replay_rows if _after_cost(row) is not None]
    for strategy in strategies:
        selected_values: list[float] = []
        direction_mismatch = 0
        selected_count = 0
        hold_count = 0
        no_trade_correct = 0
        missed_winners = 0
        false_positive_count = 0
        false_negative_count = 0
        for row in filled_rows:
            symbol = str(row.get("symbol") or "").upper()
            ac = _after_cost(row)
            if ac is None:
                continue
            if strategy == "trainer":
                action = str(_trainer_output(row).get("selected_action") or row.get("side") or "hold").lower()
            elif strategy == "no_trade_preservation":
                action = "hold"
            else:
                action = _strategy_action(strategy, features_by_symbol.get(symbol, {}))
            row_side = str(row.get("side") or _paper_intent(row).get("side") or "long").lower()
            if action in {"", "hold", "none"}:
                hold_count += 1
                if ac <= 0:
                    no_trade_correct += 1
                else:
                    missed_winners += 1
                continue
            selected_count += 1
            if action != row_side:
                direction_mismatch += 1
                continue
            selected_values.append(ac)
            if ac <= 0:
                false_positive_count += 1
            else:
                false_negative_count += 0
        mean_after = _mean(selected_values)
        ci_lower = _ci_lower(selected_values)
        sample_ok = len(selected_values) >= MIN_RECOMPUTE_OUTCOME_SAMPLE
        rows_out.append(
            {
                "strategy": strategy,
                "evaluation_mode": "DIAGNOSTIC_CURRENT_FEATURE_PROXY_NOT_PRODUCTION_BACKTEST"
                if strategy not in {"trainer", "no_trade_preservation"}
                else "REPLAY_OUTCOME_DIAGNOSTIC",
                "selected_trade_count": selected_count,
                "actionable_outcome_sample_count": len(selected_values),
                "hold_count": hold_count,
                "direction_mismatch_count": direction_mismatch,
                "after_cost_expectancy_bps": mean_after,
                "after_cost_ci_lower_bps": ci_lower,
                "false_positive_count": false_positive_count,
                "false_negative_count": false_negative_count,
                "missed_winner_count": missed_winners,
                "no_trade_correct_count": no_trade_correct,
                "no_trade_correct_rate": _rate(no_trade_correct, hold_count),
                "edge_claimed": False,
                "diagnostic_verdict": (
                    "SHADOW_DIAGNOSTIC_EDGE_CANDIDATE"
                    if sample_ok and mean_after is not None and mean_after > 0 and ci_lower is not None and ci_lower > 0
                    else "NOT_PROVEN_OR_INSUFFICIENT_SAMPLE"
                ),
            }
        )
    return {
        "schema_version": "v2_strategy_fallback_edge_comparison_status_v1",
        **_generated_block(now),
        **_safety_block(),
        "strategy_rows": rows_out,
        "strategies_are_paper_shadow_diagnostic_only": True,
        "no_live_order_authority": True,
        "feature_proxy_note": "Fallback strategies use current feature snapshots to triage candidates; they are not production historical backtests.",
    }


def _symbol_overlay_by_symbol(calibration: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = calibration.get("prediction_overlay_rows")
    if not isinstance(rows, list):
        return {}
    out: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if isinstance(row, Mapping):
            symbol = str(row.get("symbol") or "").upper()
            if symbol:
                out[symbol] = row
    return out


def build_edge_recompute_after_quality_fixes(
    *,
    symbols: list[str],
    replay_rows: list[dict[str, Any]],
    by_symbol: Mapping[str, Any],
    calibration: Mapping[str, Any],
    risk_quality: Mapping[str, Any],
    public_payloads: Mapping[str, Any],
    now: Any,
) -> dict[str, Any]:
    overlay = _symbol_overlay_by_symbol(calibration)
    negative_symbols = set((risk_quality.get("safe_paper_only_guards") or {}).get("negative_expectancy_symbol_blocklist") or [])
    pre_filter_rows = _filled_rows_for_symbols(replay_rows, set(symbols))
    pre_filter_after_values = [value for value in (_after_cost(row) for row in pre_filter_rows) if value is not None]
    eligible_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    filtered_reason_counts: Counter[str] = Counter()
    for row in replay_rows:
        ac = _after_cost(row)
        if ac is None:
            continue
        symbol = str(row.get("symbol") or "").upper()
        expected = _expected_after_cost(row)
        conf = _confidence(row)
        adjusted_conf = conf
        if symbol in overlay and overlay[symbol].get("adjusted_confidence_calibrated") is not None:
            adjusted_conf = _number(overlay[symbol].get("adjusted_confidence_calibrated"))
        if symbol in negative_symbols:
            filtered_reason_counts["NEGATIVE_EXPECTANCY_SYMBOL_BLOCK"] += 1
            continue
        if expected is None or expected < MIN_EXPECTED_AFTER_COST_BPS:
            filtered_reason_counts["MIN_EXPECTED_AFTER_COST_NOT_MET"] += 1
            continue
        if adjusted_conf is None or adjusted_conf < MIN_CONFIDENCE_AFTER_PENALTY:
            filtered_reason_counts["MIN_CONFIDENCE_AFTER_PENALTY_NOT_MET"] += 1
            continue
        eligible_by_symbol[symbol].append(row)

    initial_eligible_rows = [row for rows in eligible_by_symbol.values() for row in rows]
    max_rows_per_symbol = max(1, math.ceil(len(initial_eligible_rows) * MAX_SYMBOL_SELECTION_SHARE)) if initial_eligible_rows else 0
    diversified_rows: list[dict[str, Any]] = []
    for symbol in sorted(eligible_by_symbol):
        diversified_rows.extend(eligible_by_symbol[symbol][:max_rows_per_symbol])
        if len(eligible_by_symbol[symbol]) > max_rows_per_symbol:
            filtered_reason_counts["DIVERSIFICATION_MAX_SYMBOL_SHARE_BLOCK"] += len(eligible_by_symbol[symbol]) - max_rows_per_symbol

    after_values = [value for value in (_after_cost(row) for row in diversified_rows) if value is not None]
    drawdowns = [abs(value) for value in (_drawdown(row) for row in diversified_rows) if value is not None]
    labels = Counter(str(row.get("label") or "unknown") for row in diversified_rows)
    by_symbol_after: dict[str, list[float]] = defaultdict(list)
    for row in diversified_rows:
        ac = _after_cost(row)
        if ac is not None:
            by_symbol_after[str(row.get("symbol") or "").upper()].append(ac)
    by_symbol_edge = [
        {
            "symbol": symbol,
            "sample_count": len(values),
            "after_cost_expectancy_bps": _mean(values),
            "after_cost_ci_lower_bps": _ci_lower(values),
        }
        for symbol, values in sorted(by_symbol_after.items())
    ]
    mean_after = _mean(after_values)
    ci_lower = _ci_lower(after_values)
    validation_rows = None
    trainer_payload = public_payloads["trainer_live_loop"]["payload"]
    if isinstance(trainer_payload, Mapping):
        validation_rows = int(trainer_payload.get("validation_rows") or 0)

    sample_ok = len(after_values) >= MIN_RECOMPUTE_OUTCOME_SAMPLE
    validation_ok = validation_rows is not None and validation_rows >= MIN_VALIDATION_ROWS
    after_cost_ok = mean_after is not None and mean_after > 0 and ci_lower is not None and ci_lower > 0
    if not sample_ok or not validation_ok:
        recommendation = "BLOCK_LIVE_MODEL_SIGNAL_QUALITY_NOT_READY"
    elif not after_cost_ok:
        recommendation = "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN"
    elif risk_quality.get("safe_paper_only_guards", {}).get("preserve_live_gate") != "blocked_human_only":
        recommendation = "BLOCK_LIVE_RISK_CAPS_OPERATOR_REQUIRED"
    else:
        recommendation = "CANARY_OPERATOR_DECISION_REQUIRED"

    total_decision_errors = labels.get("false_positive", 0) + labels.get("false_negative", 0) + labels.get("correct_no_trade", 0)
    return {
        "schema_version": "v2_dynamic_93_edge_recompute_after_quality_fixes_v1",
        **_generated_block(now),
        **_safety_block(),
        "quality_overlay": {
            "min_expected_move_after_cost_bps": MIN_EXPECTED_AFTER_COST_BPS,
            "min_confidence_after_penalty": MIN_CONFIDENCE_AFTER_PENALTY,
            "negative_expectancy_symbol_blocklist": sorted(negative_symbols),
            "max_symbol_selection_share": MAX_SYMBOL_SELECTION_SHARE,
            "max_top5_selection_share": MAX_TOP5_SELECTION_SHARE,
            "applies_to_live_or_canary": False,
        },
        "pre_filter_outcome_rows": len(pre_filter_rows),
        "pre_filter_after_cost_expectancy_bps": _mean(pre_filter_after_values),
        "pre_filter_after_cost_ci_lower_bps": _ci_lower(pre_filter_after_values),
        "initial_eligible_rows": len(initial_eligible_rows),
        "candidate_count": len(diversified_rows),
        "selected_symbol_count": len(by_symbol_after),
        "filtered_reason_counts": dict(filtered_reason_counts),
        "after_cost_expectancy_bps": mean_after,
        "after_cost_ci_lower_bps": ci_lower,
        "validation_rows": validation_rows,
        "false_positive_rate": _rate(labels.get("false_positive", 0), total_decision_errors),
        "false_negative_rate": _rate(labels.get("false_negative", 0), total_decision_errors),
        "downside_recall": _rate(labels.get("correct_no_trade", 0), labels.get("correct_no_trade", 0) + labels.get("false_positive", 0)),
        "max_drawdown_bps": max(drawdowns) if drawdowns else None,
        "label_counts": dict(labels),
        "by_symbol_edge": by_symbol_edge,
        "edge_proof_passed_after_quality_fixes": bool(sample_ok and validation_ok and after_cost_ok),
        "live_readiness_recommendation": recommendation,
        "allowed_recommendations": [
            "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
            "BLOCK_LIVE_RISK_CAPS_OPERATOR_REQUIRED",
            "BLOCK_LIVE_MODEL_SIGNAL_QUALITY_NOT_READY",
            "CANARY_OPERATOR_DECISION_REQUIRED",
        ],
        "no_fake_edge": True,
        "negative_after_cost_expectancy_visible": (
            (mean_after is not None and mean_after < 0)
            or (_mean(pre_filter_after_values) is not None and float(_mean(pre_filter_after_values) or 0.0) < 0)
        ),
    }


def build_website_sync_status(*, repo_root: Path, now: Any) -> dict[str, Any]:
    pages = {
        "edge_page": repo_root / "v2/frontend/src/pages/replay/index.tsx",
        "trainer_admin_page": repo_root / "v2/frontend/src/pages/trainer-admin/index.tsx",
        "trainer_prediction_page": repo_root / "v2/frontend/src/pages/trainer-prediction-monitor/index.tsx",
        "symbols_page": repo_root / "v2/frontend/src/pages/symbols/index.tsx",
        "market_intelligence_page": repo_root / "v2/frontend/src/pages/market-intelligence/index.tsx",
        "live_readiness_page": repo_root / "v2/frontend/src/pages/live-readiness/index.tsx",
        "paper_trading_page": repo_root / "v2/frontend/src/pages/paper-trading/index.tsx",
    }
    page_rows: list[dict[str, Any]] = []
    for name, path in pages.items():
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            text = ""
        page_rows.append(
            {
                "page": name,
                "path": str(path),
                "wired": LANE_ID in text or "EdgeRecoveryQualityPanel" in text,
            }
        )
    return {
        "schema_version": "v2_dynamic_93_edge_recovery_website_sync_status_v1",
        **_generated_block(now),
        **_safety_block(),
        "website_sync_status": "WEBSITE_SYNCED" if all(row["wired"] for row in page_rows) else "WEBSITE_SYNC_BLOCKED",
        "page_rows": page_rows,
        "shows_top_positive_negative_symbols": True,
        "shows_public_intel_contribution": True,
        "shows_trainer_calibration": True,
        "shows_strategy_fallback_comparison": True,
        "shows_risk_paper_block_reasons": True,
        "shows_why_live_is_blocked": True,
        "shows_next_automatic_action": True,
    }


def _safety_ok(payloads: Iterable[Mapping[str, Any]]) -> bool:
    for payload in payloads:
        if payload.get("live_gate") != "blocked_human_only":
            return False
        if payload.get("live_symbols") != []:
            return False
        if payload.get("execution_live_symbols") not in ([], None):
            return False
        for key in (
            "approves_live",
            "approves_canary",
            "writes_legacy_redis",
            "writes_old_redis",
            "writes_exchange_orders",
            "places_exchange_orders",
            "places_real_order",
            "calls_exchange_mutation",
            "calls_test_order_endpoint",
            "leverage_changed",
            "margin_mode_changed",
            "execution_mutation_enabled",
        ):
            if bool(payload.get(key)):
                return False
    return True


def _decide_go_no_go(
    *,
    symbols: list[str],
    edge_recompute: Mapping[str, Any],
    website_sync: Mapping[str, Any],
    payloads: Iterable[Mapping[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    blockers: list[dict[str, Any]] = []
    if len(symbols) != TARGET_DYNAMIC_SYMBOL_COUNT:
        blockers.append({"id": "SYMBOL_COUNT_NOT_93", "detail": f"symbol_count={len(symbols)}"})
    if not edge_recompute.get("edge_proof_passed_after_quality_fixes"):
        blockers.append(
            {
                "id": "PAPER_BACKTEST_EDGE_NOT_PROVEN_AFTER_QUALITY_FIXES",
                "detail": edge_recompute.get("live_readiness_recommendation"),
            }
        )
    if website_sync.get("website_sync_status") != "WEBSITE_SYNCED":
        blockers.append({"id": "WEBSITE_SYNC_BLOCKED", "detail": "one or more requested pages are not wired"})
    if not _safety_ok(payloads):
        blockers.append({"id": "SAFETY_PIN_VIOLATION", "detail": "one or more non-execution pins changed"})
    return (GO_NO_GO_BLOCKED if blockers else GO_NO_GO_READY), blockers


def build_operator_dashboard_payload(
    *,
    go_no_go: str,
    blockers: list[dict[str, Any]],
    by_symbol: Mapping[str, Any],
    public_intel: Mapping[str, Any],
    calibration: Mapping[str, Any],
    risk_quality: Mapping[str, Any],
    strategy: Mapping[str, Any],
    edge_recompute: Mapping[str, Any],
    website_sync: Mapping[str, Any],
    now: Any,
) -> dict[str, Any]:
    top_positive = by_symbol.get("top_positive_symbols") or []
    top_negative = by_symbol.get("top_negative_symbols") or []
    mode_rows = public_intel.get("comparison_modes") or []
    strategy_rows = strategy.get("strategy_rows") or []
    return {
        "schema_version": "v2_dynamic_93_edge_recovery_signal_quality_burndown_dashboard_v1",
        **_generated_block(now),
        **_safety_block(),
        "go_no_go": go_no_go,
        "status": "BLOCKED" if go_no_go == GO_NO_GO_BLOCKED else "READY",
        "blockers": blockers,
        "summary": {
            "symbol_count": by_symbol.get("symbol_count"),
            "classification_counts": by_symbol.get("classification_counts"),
            "top_positive_symbols": [
                {"symbol": row.get("symbol"), "after_cost_expectancy_bps": row.get("after_cost_expectancy_bps")}
                for row in top_positive[:8]
                if isinstance(row, Mapping)
            ],
            "top_negative_symbols": [
                {"symbol": row.get("symbol"), "after_cost_expectancy_bps": row.get("after_cost_expectancy_bps")}
                for row in top_negative[:8]
                if isinstance(row, Mapping)
            ],
            "public_intel_modes": [
                {
                    "mode": row.get("mode"),
                    "outcome_sample_count": row.get("outcome_sample_count"),
                    "after_cost_expectancy_bps": row.get("after_cost_expectancy_bps"),
                    "after_cost_proof_state": row.get("after_cost_proof_state"),
                }
                for row in mode_rows
                if isinstance(row, Mapping)
            ],
            "calibration_error_bps": calibration.get("calibration_error_bps"),
            "high_confidence_loser_count": len(calibration.get("high_confidence_losers") or []),
            "risk_block_category_counts": risk_quality.get("risk_block_category_counts"),
            "best_diagnostic_strategy": max(
                [row for row in strategy_rows if isinstance(row, Mapping)],
                key=lambda row: row.get("after_cost_expectancy_bps")
                if isinstance(row.get("after_cost_expectancy_bps"), (int, float))
                else -1e9,
                default={},
            ),
            "after_quality_fixes_expectancy_bps": edge_recompute.get("after_cost_expectancy_bps"),
            "after_quality_fixes_ci_lower_bps": edge_recompute.get("after_cost_ci_lower_bps"),
            "pre_filter_after_cost_expectancy_bps": edge_recompute.get("pre_filter_after_cost_expectancy_bps"),
            "pre_filter_after_cost_ci_lower_bps": edge_recompute.get("pre_filter_after_cost_ci_lower_bps"),
            "after_quality_fixes_candidate_count": edge_recompute.get("candidate_count"),
            "primary_live_recommendation": edge_recompute.get("live_readiness_recommendation"),
            "website_sync_status": website_sync.get("website_sync_status"),
            "next_automatic_action": "Continue paper/shadow outcome mining with quality overlay; do not enable execution.",
        },
        "by_symbol_edge_attribution": by_symbol,
        "public_intel_signal_contribution": public_intel,
        "trainer_confidence_calibration": calibration,
        "risk_paper_decision_quality": risk_quality,
        "strategy_fallback_edge_comparison": strategy,
        "edge_recompute_after_quality_fixes": edge_recompute,
        "website_sync": website_sync,
        "why_live_is_blocked": [
            "live_gate=blocked_human_only",
            "live_symbols=[]",
            "execution_live_symbols=[]",
            str(edge_recompute.get("live_readiness_recommendation") or "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN"),
        ],
    }


def _write_report(path: Path, dashboard: Mapping[str, Any]) -> None:
    summary = dashboard.get("summary") or {}
    blockers = dashboard.get("blockers") or []
    lines = [
        "# V2 Dynamic 93 Edge Recovery And Signal Quality Burndown",
        "",
        f"Generated EST: {dashboard.get('generated_est')}",
        "",
        f"GO/NO-GO: `{dashboard.get('go_no_go')}`",
        "",
        "## Summary",
        "",
        f"- symbol_count: `{summary.get('symbol_count')}`",
        f"- classification_counts: `{summary.get('classification_counts')}`",
        f"- after_quality_fixes_expectancy_bps: `{summary.get('after_quality_fixes_expectancy_bps')}`",
        f"- after_quality_fixes_ci_lower_bps: `{summary.get('after_quality_fixes_ci_lower_bps')}`",
        f"- pre_filter_after_cost_expectancy_bps: `{summary.get('pre_filter_after_cost_expectancy_bps')}`",
        f"- pre_filter_after_cost_ci_lower_bps: `{summary.get('pre_filter_after_cost_ci_lower_bps')}`",
        f"- primary_live_recommendation: `{summary.get('primary_live_recommendation')}`",
        f"- website_sync_status: `{summary.get('website_sync_status')}`",
        f"- next_automatic_action: `{summary.get('next_automatic_action')}`",
        "",
        "## Blockers",
        "",
    ]
    if blockers:
        for blocker in blockers:
            lines.append(f"- `{blocker.get('id')}`: {blocker.get('detail')}")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- live_gate: `blocked_human_only`",
            "- live_symbols: `[]`",
            "- execution_live_symbols: `[]`",
            "- writes_legacy_redis: `false`",
            "- writes_exchange_orders: `false`",
            "- exchange mutation: `false`",
            "- quality overlay scope: `paper/shadow only`",
            "",
        ]
    )
    _write_text(path, "\n".join(lines))


def _write_outputs(
    *,
    paths: PacketPaths,
    by_symbol: Mapping[str, Any],
    public_intel: Mapping[str, Any],
    calibration: Mapping[str, Any],
    risk_quality: Mapping[str, Any],
    strategy: Mapping[str, Any],
    edge_recompute: Mapping[str, Any],
    dashboard: Mapping[str, Any],
) -> None:
    for out_dir in (paths.worklog_dir, paths.public_dir, paths.operator_runtime_dir):
        _write_json(out_dir / "v2_dynamic_93_by_symbol_edge_attribution.json", by_symbol)
        _write_json(out_dir / "v2_public_intel_signal_contribution_status.json", public_intel)
        _write_json(out_dir / "v2_trainer_confidence_calibration_status.json", calibration)
        _write_json(out_dir / "v2_risk_paper_decision_quality_status.json", risk_quality)
        _write_json(out_dir / "v2_strategy_fallback_edge_comparison_status.json", strategy)
        _write_json(out_dir / "v2_dynamic_93_edge_recompute_after_quality_fixes.json", edge_recompute)
        _write_json(out_dir / "operator_dashboard_payload.json", dashboard)
        _write_text(out_dir / "GO_NO_GO.md", str(dashboard.get("go_no_go")) + "\n")
    report_name = "V2_DYNAMIC_93_EDGE_RECOVERY_AND_SIGNAL_QUALITY_BURNDOWN_REPORT.md"
    _write_report(paths.worklog_dir / report_name, dashboard)
    _write_report(paths.public_dir / report_name, dashboard)
    _write_report(paths.operator_runtime_dir / report_name, dashboard)


def run_once(
    *,
    repo_root: Path = REPO_ROOT,
    redis_client_override: Any | None = None,
    write_files: bool = True,
) -> dict[str, Any]:
    now = _now()
    redis_client = redis_client_override if redis_client_override is not None else _connect_redis()
    symbols, _symbol_provenance = _resolve_runtime_symbols(repo_root)
    public_payloads = _load_public_payloads(repo_root)
    replay_rows, replay_status = _load_replay_rows(_replay_bundle_path(repo_root), set(symbols))
    by_symbol = build_by_symbol_edge_attribution(
        symbols=symbols,
        replay_rows=replay_rows,
        redis_client=redis_client,
        now=now,
    )
    by_symbol["replay_bundle_file_status"] = replay_status
    public_intel = build_public_intel_signal_contribution_status(
        symbols=symbols,
        replay_rows=replay_rows,
        redis_client=redis_client,
        public_payloads=public_payloads,
        now=now,
    )
    calibration = build_trainer_confidence_calibration_status(
        symbols=symbols,
        replay_rows=replay_rows,
        by_symbol=by_symbol,
        redis_client=redis_client,
        public_payloads=public_payloads,
        now=now,
    )
    risk_quality = build_risk_paper_decision_quality_status(
        symbols=symbols,
        replay_rows=replay_rows,
        by_symbol=by_symbol,
        public_payloads=public_payloads,
        now=now,
    )
    strategy = build_strategy_fallback_edge_comparison_status(
        symbols=symbols,
        replay_rows=replay_rows,
        redis_client=redis_client,
        now=now,
    )
    edge_recompute = build_edge_recompute_after_quality_fixes(
        symbols=symbols,
        replay_rows=replay_rows,
        by_symbol=by_symbol,
        calibration=calibration,
        risk_quality=risk_quality,
        public_payloads=public_payloads,
        now=now,
    )
    website_sync = build_website_sync_status(repo_root=repo_root, now=now)
    all_payloads = (by_symbol, public_intel, calibration, risk_quality, strategy, edge_recompute, website_sync)
    go_no_go, blockers = _decide_go_no_go(
        symbols=symbols,
        edge_recompute=edge_recompute,
        website_sync=website_sync,
        payloads=all_payloads,
    )
    dashboard = build_operator_dashboard_payload(
        go_no_go=go_no_go,
        blockers=blockers,
        by_symbol=by_symbol,
        public_intel=public_intel,
        calibration=calibration,
        risk_quality=risk_quality,
        strategy=strategy,
        edge_recompute=edge_recompute,
        website_sync=website_sync,
        now=now,
    )

    if write_files:
        _write_outputs(
            paths=default_paths(repo_root),
            by_symbol=by_symbol,
            public_intel=public_intel,
            calibration=calibration,
            risk_quality=risk_quality,
            strategy=strategy,
            edge_recompute=edge_recompute,
            dashboard=dashboard,
        )
    return dashboard


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_dynamic_93_edge_recovery_signal_quality_burndown")
    parser.add_argument("--once", action="store_true", default=True)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-files", action="store_true")
    args = parser.parse_args(argv)

    while True:
        payload = run_once(write_files=not args.no_files)
        summary = {
            "go_no_go": payload["go_no_go"],
            "symbol_count": payload["summary"]["symbol_count"],
            "after_quality_fixes_expectancy_bps": payload["summary"]["after_quality_fixes_expectancy_bps"],
            "primary_live_recommendation": payload["summary"]["primary_live_recommendation"],
            "live_gate": payload["live_gate"],
            "live_symbols": payload["live_symbols"],
            "execution_live_symbols": payload["execution_live_symbols"],
        }
        print(json.dumps(payload if args.json else summary, indent=2, sort_keys=True, default=str))
        if not args.loop:
            return 0
        try:
            time.sleep(max(60, int(args.interval_seconds)))
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    sys.exit(main())
