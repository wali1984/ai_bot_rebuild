"""Read-only pipeline trust verifier.

This CLI inspects stored JSON/JSONL records and, optionally, Redis snapshots using read-only
commands. It writes pipeline_trust_report.json and pipeline_trust_report.md and exits non-zero
when critical trust failures are detected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

CRITICAL_EXIT_TITLES = {
    "look-ahead leakage detected",
    "future feature use detected",
    "unfinished higher-timeframe candle detected",
    "dirty training sample accepted",
    "invalid position transition detected",
}

DEFAULT_REDIS_PATTERNS = (
    "v2:market:ohlcv:*",
    "v2:market:prices:*",
    "v2:features:*",
    "v2:technical_analysis:*",
    "v2:prediction:*",
    "v2:signals:paper:*",
    "v2:orchestrator:*",
    "v2:risk:*",
    "v2:paper:*",
    "v2:trainer:*",
    "v2:live_order_transport:*",
    "latest:coinank:*",
)

TIMEFRAME_SECONDS = {
    "1s": 1,
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "1d": 86400,
}

HIGHER_TIMEFRAMES = {"5m", "15m", "30m", "1h", "2h", "4h", "1d"}
REQUIRED_ALIGNMENT_TIMEFRAMES = ("1m", "5m", "15m", "1h")

AFFECTED_MODULES = {
    "candles": [
        "v2/backend/app/services/market_ingest/service.py",
        "v2/backend/app/cli/v2_binance_kline_wss_loop.py",
        "v2/backend/app/cli/v2_feature_pipeline_native_loop.py",
        "v2/backend/app/services/native_trainer/hybrid_cuda_trainer/tensor_builder.py",
    ],
    "mtf": [
        "v2/backend/app/services/feature_pipeline_native/service.py",
        "v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py",
        "v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py",
    ],
    "features": [
        "v2/backend/app/services/feature_pipeline_native/service.py",
        "v2/backend/app/cli/v2_feature_pipeline_native_loop.py",
        "v2/backend/app/services/native_trainer/hybrid_cuda_trainer/tensor_builder.py",
    ],
    "masa_ppo": [
        "v2/backend/app/services/native_trainer/hybrid_cuda_trainer/masa.py",
        "v2/backend/app/services/native_trainer/hybrid_cuda_trainer/model.py",
        "v2/backend/app/services/rl_core/observation_schema.py",
    ],
    "training": [
        "v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py",
        "v2/backend/app/services/native_trainer/hybrid_cuda_trainer/ppo_trainer.py",
        "v2/backend/app/services/market_state_integrity/sample_rejection.py",
    ],
    "execution": [
        "v2/backend/app/cli/v2_paper_execution_worker.py",
        "v2/backend/app/services/live_gate/binance_live_order_transport.py",
        "v2/backend/app/services/account_position_monitor/service.py",
    ],
    "config": [
        "v2/backend/app/api/v1/config_admin.py",
        "v2/backend/app/cli/v2_config_admin_manager.py",
        "v2/backend/app/services/config_admin/service.py",
        "v2/backend/app/api/v2/trainer.py",
    ],
    "parity": [
        "v2/backend/app/services/replay_backtest_runner/service.py",
        "v2/backend/app/services/edge_proof/replay_miner.py",
        "v2/backend/app/cli/v2_paper_execution_worker.py",
        "v2/backend/app/services/live_gate/binance_live_order_transport.py",
    ],
}


@dataclass
class SourceRecord:
    source: str
    key: str | None
    value: Any


@dataclass
class Finding:
    check_id: str
    status: str
    severity: str
    title: str
    affected_modules: list[str] = field(default_factory=list)
    affected_symbols: list[str] = field(default_factory=list)
    affected_timeframes: list[str] = field(default_factory=list)
    example_records: list[dict[str, Any]] = field(default_factory=list)
    recommended_fix: str = ""

    @property
    def is_critical_failure(self) -> bool:
        return self.status == "FAIL" and self.severity == "Critical"


@dataclass
class Candle:
    source_record: str
    exchange: str
    symbol: str
    timeframe: str
    open_time: int | None
    close_time: int | None
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    final: bool | None
    raw: dict[str, Any]


@dataclass
class TrustReport:
    generated_at: str
    mode: str
    data_sources: list[str]
    findings: list[Finding]
    summaries: dict[str, Any]

    def to_jsonable(self) -> dict[str, Any]:
        data = asdict(self)
        data["summary"] = {
            "total_findings": len(self.findings),
            "critical_failures": sum(1 for f in self.findings if f.is_critical_failure),
            "failures": sum(1 for f in self.findings if f.status == "FAIL"),
            "warnings": sum(1 for f in self.findings if f.status == "WARN"),
            "passes": sum(1 for f in self.findings if f.status == "PASS"),
        }
        return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="verify_pipeline_trust",
        description="Read-only verifier for pipeline point-in-time trust, data integrity, and parity.",
    )
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        help="JSON/JSONL file or directory to inspect. Can be repeated.",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory for pipeline_trust_report.json and pipeline_trust_report.md.",
    )
    parser.add_argument(
        "--redis-url",
        default=os.getenv("REDIS_URL", ""),
        help="Optional Redis URL. Only read commands are used.",
    )
    parser.add_argument(
        "--redis-pattern",
        action="append",
        default=[],
        help="Redis SCAN pattern. Defaults to known v2 pipeline patterns when --redis-url is set.",
    )
    parser.add_argument("--max-files", type=int, default=500)
    parser.add_argument("--max-redis-keys", type=int, default=5000)
    parser.add_argument("--max-examples", type=int, default=5)
    parser.add_argument("--source-disagreement-bps", type=float, default=50.0)
    parser.add_argument(
        "--strict-unknown",
        action="store_true",
        help="Treat missing evidence sections as critical failures.",
    )
    args = parser.parse_args(argv)

    records = load_records(args)
    report = verify_records(records, args)
    write_reports(report, Path(args.output_dir))
    critical_failures = sum(1 for finding in report.findings if finding.is_critical_failure)
    return 1 if critical_failures else 0


def load_records(args: argparse.Namespace) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    seen_files = 0
    for input_path in args.input:
        path = Path(input_path)
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if seen_files >= args.max_files:
                    break
                if child.suffix.lower() in {".json", ".jsonl", ".ndjson"}:
                    records.extend(read_json_records(child))
                    seen_files += 1
        elif path.is_file():
            records.extend(read_json_records(path))
            seen_files += 1

    if args.redis_url:
        patterns = tuple(args.redis_pattern) if args.redis_pattern else DEFAULT_REDIS_PATTERNS
        records.extend(read_redis_records(args.redis_url, patterns, args.max_redis_keys))
    return records


def read_json_records(path: Path) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    try:
        if path.suffix.lower() in {".jsonl", ".ndjson"}:
            with path.open("r", encoding="utf-8") as handle:
                for index, line in enumerate(handle, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError as exc:
                        records.append(
                            SourceRecord(str(path), f"json_decode_error:{index}", {"error": str(exc)})
                        )
                        continue
                    records.append(SourceRecord(str(path), infer_key(value), value))
        else:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            records.extend(flatten_top_level_json(str(path), value))
    except OSError as exc:
        records.append(SourceRecord(str(path), "read_error", {"error": str(exc)}))
    except json.JSONDecodeError as exc:
        records.append(SourceRecord(str(path), "json_decode_error", {"error": str(exc)}))
    return records


def flatten_top_level_json(source: str, value: Any) -> list[SourceRecord]:
    if isinstance(value, list):
        return [SourceRecord(source, infer_key(item), item) for item in value]
    if isinstance(value, dict):
        child_records = [
            SourceRecord(source, str(key), child)
            for key, child in value.items()
            if isinstance(child, (dict, list))
        ]
        is_container = bool(child_records) and not (
            looks_like_candle(value, None)
            or looks_like_feature(value, None)
            or looks_like_decision(value, None)
            or looks_like_training_sample(value, None)
            or looks_like_execution(value, None)
            or looks_like_config(value, None)
        )
        if is_container:
            return child_records
        records = [SourceRecord(source, infer_key(value), value)]
        for key, child in value.items():
            if isinstance(child, (dict, list)):
                records.append(SourceRecord(source, str(key), child))
        return records
    return [SourceRecord(source, None, value)]


def read_redis_records(redis_url: str, patterns: Iterable[str], max_keys: int) -> list[SourceRecord]:
    try:
        import redis  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on optional environment
        return [SourceRecord("redis", "redis_import_error", {"error": str(exc)})]

    records: list[SourceRecord] = []
    client = redis.Redis.from_url(redis_url, decode_responses=True)
    seen: set[str] = set()
    try:
        for pattern in patterns:
            for key in client.scan_iter(match=pattern, count=500):
                if key in seen:
                    continue
                seen.add(key)
                if len(seen) > max_keys:
                    return records
                records.append(SourceRecord("redis", key, read_redis_value(client, key)))
    except Exception as exc:  # pragma: no cover - depends on optional environment
        records.append(SourceRecord("redis", "redis_read_error", {"error": str(exc)}))
    return records


def read_redis_value(client: Any, key: str) -> Any:
    value_type = client.type(key)
    if isinstance(value_type, bytes):
        value_type = value_type.decode("utf-8", errors="replace")
    if value_type == "string":
        return parse_json_maybe(client.get(key))
    if value_type == "hash":
        return {field: parse_json_maybe(value) for field, value in client.hgetall(key).items()}
    if value_type == "list":
        return [parse_json_maybe(value) for value in client.lrange(key, 0, 999)]
    if value_type == "stream":
        rows = []
        for item_id, fields in client.xrevrange(key, count=1000):
            rows.append({"id": item_id, **{k: parse_json_maybe(v) for k, v in fields.items()}})
        return rows
    if value_type == "zset":
        return [parse_json_maybe(value) for value in client.zrange(key, 0, 999)]
    if value_type == "set":
        return sorted(parse_json_maybe(value) for value in client.smembers(key))
    return None


def parse_json_maybe(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    if text[0] not in "[{\"-0123456789tfn":
        return value
    try:
        return json.loads(text)
    except Exception:
        return value


def verify_records(records: list[SourceRecord], args: argparse.Namespace) -> TrustReport:
    candles = extract_candles(records)
    features = extract_features(records)
    decisions = extract_decisions(records)
    training_samples = extract_training_samples(records)
    execution_records = extract_execution_records(records)
    config_records = extract_config_records(records)

    findings: list[Finding] = []
    summaries: dict[str, Any] = {}

    candle_findings, candle_summary = check_candle_integrity(candles, args)
    findings.extend(candle_findings)
    summaries["candle_integrity"] = candle_summary

    mtf_findings, mtf_summary = check_multi_timeframe_alignment(candles, decisions, args)
    findings.extend(mtf_findings)
    summaries["multi_timeframe_alignment"] = mtf_summary

    feature_findings, feature_summary = check_feature_integrity(features, args)
    findings.extend(feature_findings)
    summaries["feature_integrity"] = feature_summary

    masa_ppo_findings, masa_ppo_summary = check_masa_ppo_consistency(decisions, args)
    findings.extend(masa_ppo_findings)
    summaries["masa_ppo_consistency"] = masa_ppo_summary

    training_findings, training_summary = check_training_samples(training_samples, args)
    findings.extend(training_findings)
    summaries["training_samples"] = training_summary

    execution_findings, execution_summary = check_execution_records(execution_records, args)
    findings.extend(execution_findings)
    summaries["position_execution"] = execution_summary

    snapshot_findings = check_snapshot_contract(decisions, execution_records, args)
    findings.extend(snapshot_findings)

    schema_field_findings = check_trust_schema_required_fields(records, args)
    findings.extend(schema_field_findings)

    config_findings, config_summary = check_config_records(config_records, args)
    findings.extend(config_findings)
    summaries["config_admin"] = config_summary

    parity_findings, parity_summary = check_live_vs_backtest_parity(records, args)
    findings.extend(parity_findings)
    summaries["live_vs_backtest_parity"] = parity_summary

    if args.strict_unknown:
        promote_unknowns_to_critical(findings)

    return TrustReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        mode="read_only",
        data_sources=sorted({record.source for record in records}),
        findings=findings,
        summaries=summaries,
    )


def check_candle_integrity(candles: list[Candle], args: argparse.Namespace) -> tuple[list[Finding], dict[str, Any]]:
    findings: list[Finding] = []
    groups: dict[tuple[str, str, str], list[Candle]] = defaultdict(list)
    for candle in candles:
        groups[(candle.exchange, candle.symbol, candle.timeframe)].append(candle)

    summary: dict[str, Any] = {"total_candles": len(candles), "groups": []}
    if not candles:
        findings.append(
            Finding(
                "candle_integrity.no_data",
                "WARN",
                "High",
                "no candle records found",
                AFFECTED_MODULES["candles"],
                recommended_fix="Provide JSON/JSONL snapshots or Redis access containing OHLCV candle records.",
            )
        )
        return findings, summary

    for (exchange, symbol, timeframe), rows in sorted(groups.items()):
        interval = timeframe_to_seconds(timeframe)
        original_times = [c.open_time for c in rows if c.open_time is not None]
        sorted_rows = sorted((c for c in rows if c.open_time is not None), key=lambda c: c.open_time or 0)
        counts_by_time: dict[int, int] = defaultdict(int)
        for open_time in original_times:
            counts_by_time[open_time] += 1
        duplicates = sum(count - 1 for count in counts_by_time.values() if count > 1)
        out_of_order = sum(
            1 for previous, current in zip(original_times, original_times[1:], strict=False) if current < previous
        )
        missing = 0
        gaps: list[dict[str, Any]] = []
        if interval:
            expected_ms = interval * 1000
            for previous, current in zip(sorted_rows, sorted_rows[1:], strict=False):
                if previous.open_time is None or current.open_time is None:
                    continue
                delta = normalize_ms(current.open_time) - normalize_ms(previous.open_time)
                if delta > expected_ms:
                    missing_here = max(0, int(round(delta / expected_ms)) - 1)
                    missing += missing_here
                    gaps.append(
                        {
                            "from_open_time": previous.open_time,
                            "to_open_time": current.open_time,
                            "missing_candles": missing_here,
                        }
                    )

        unfinished_final = []
        unfinished_in_closed_store = []
        abnormal = []
        non_positive_volume = []
        for candle in rows:
            if candle.final is True and not candle_has_valid_close(candle, interval):
                unfinished_final.append(candle.raw)
            if candle.final is False and is_closed_candle_key(candle.source_record):
                unfinished_in_closed_store.append(candle.raw)
            if has_abnormal_ohlc(candle):
                abnormal.append(candle.raw)
            if candle.volume is not None and candle.volume <= 0:
                non_positive_volume.append(candle.raw)

        group_summary = {
            "exchange": exchange,
            "symbol": symbol,
            "timeframe": timeframe,
            "total_candles": len(rows),
            "missing_candles": missing,
            "duplicate_candles": duplicates,
            "out_of_order_candles": out_of_order,
            "unfinished_candles_marked_final": len(unfinished_final),
            "unfinished_candles_in_closed_store": len(unfinished_in_closed_store),
            "timestamp_gaps": gaps[: args.max_examples],
            "abnormal_ohlc_values": len(abnormal),
            "zero_or_negative_volume": len(non_positive_volume),
        }
        summary["groups"].append(group_summary)

        affected_symbols = [symbol] if symbol != "unknown" else []
        affected_timeframes = [timeframe] if timeframe != "unknown" else []
        if duplicates:
            findings.append(
                Finding(
                    "candle_integrity.duplicates",
                    "FAIL",
                    "High",
                    "duplicate candles detected",
                    AFFECTED_MODULES["candles"],
                    affected_symbols,
                    affected_timeframes,
                    example_records=[{"exchange": exchange, **group_summary}],
                    recommended_fix="Deduplicate candles by exchange, symbol, timeframe, and candle_open_time before feature publication.",
                )
            )
        if missing:
            findings.append(
                Finding(
                    "candle_integrity.missing",
                    "FAIL",
                    "High",
                    "missing candle gaps detected",
                    AFFECTED_MODULES["candles"],
                    affected_symbols,
                    affected_timeframes,
                    example_records=[{"exchange": exchange, **group_summary}],
                    recommended_fix="Add gap detection/backfill quarantine before a candle sequence is marked feature-ready.",
                )
            )
        if out_of_order:
            findings.append(
                Finding(
                    "candle_integrity.out_of_order",
                    "FAIL",
                    "High",
                    "out-of-order candles detected",
                    AFFECTED_MODULES["candles"],
                    affected_symbols,
                    affected_timeframes,
                    example_records=[{"exchange": exchange, **group_summary}],
                    recommended_fix="Sort and validate monotonic candle_open_time before writing closed-candle storage.",
                )
            )
        if unfinished_final or unfinished_in_closed_store:
            findings.append(
                Finding(
                    "candle_integrity.unfinished_final",
                    "FAIL",
                    "Critical",
                    "unfinished candles marked final or stored in closed-candle path",
                    AFFECTED_MODULES["candles"],
                    affected_symbols,
                    affected_timeframes,
                    example_records=(unfinished_final + unfinished_in_closed_store)[: args.max_examples],
                    recommended_fix="Separate current/open candles from final OHLCV keys and require exchange close confirmation before final storage.",
                )
            )
        if abnormal:
            findings.append(
                Finding(
                    "candle_integrity.abnormal_ohlc",
                    "FAIL",
                    "Critical",
                    "abnormal OHLC values detected",
                    AFFECTED_MODULES["candles"],
                    affected_symbols,
                    affected_timeframes,
                    example_records=abnormal[: args.max_examples],
                    recommended_fix="Reject candles with non-positive prices or OHLC invariants that do not satisfy low <= open/close <= high.",
                )
            )
        if non_positive_volume:
            findings.append(
                Finding(
                    "candle_integrity.non_positive_volume",
                    "FAIL",
                    "Medium",
                    "zero or negative volume candles detected",
                    AFFECTED_MODULES["candles"],
                    affected_symbols,
                    affected_timeframes,
                    example_records=non_positive_volume[: args.max_examples],
                    recommended_fix="Quarantine zero/negative-volume candles unless the source explicitly documents valid zero-volume intervals.",
                )
            )

    disagreement_findings = check_source_disagreement(groups, args)
    findings.extend(disagreement_findings)

    if not any(f.check_id.startswith("candle_integrity.") and f.status == "FAIL" for f in findings):
        findings.append(
            Finding(
                "candle_integrity.pass",
                "PASS",
                "Info",
                "candle integrity checks passed for loaded records",
                AFFECTED_MODULES["candles"],
                recommended_fix="No action for loaded records. Keep this check in CI/operations with representative data.",
            )
        )
    return findings, summary


def check_source_disagreement(
    groups: dict[tuple[str, str, str], list[Candle]], args: argparse.Namespace
) -> list[Finding]:
    by_symbol_tf: dict[tuple[str, str], dict[str, dict[int, Candle]]] = defaultdict(lambda: defaultdict(dict))
    for (exchange, symbol, timeframe), rows in groups.items():
        for candle in rows:
            if candle.open_time is not None:
                by_symbol_tf[(symbol, timeframe)][exchange][normalize_ms(candle.open_time)] = candle

    findings: list[Finding] = []
    threshold = args.source_disagreement_bps / 10000.0
    examples: list[dict[str, Any]] = []
    affected_symbols: set[str] = set()
    affected_timeframes: set[str] = set()
    for (symbol, timeframe), exchanges in by_symbol_tf.items():
        if len(exchanges) < 2:
            continue
        common_times = set.intersection(*(set(rows) for rows in exchanges.values()))
        for open_time in sorted(common_times):
            closes = {
                exchange: candle.close
                for exchange, rows in exchanges.items()
                for candle in [rows[open_time]]
                if candle.close is not None and candle.close > 0
            }
            if len(closes) < 2:
                continue
            values = list(closes.values())
            mid = sum(values) / len(values)
            if mid and (max(values) - min(values)) / mid > threshold:
                affected_symbols.add(symbol)
                affected_timeframes.add(timeframe)
                examples.append({"symbol": symbol, "timeframe": timeframe, "open_time": open_time, "closes": closes})
                if len(examples) >= args.max_examples:
                    break
    if examples:
        findings.append(
            Finding(
                "candle_integrity.source_disagreement",
                "FAIL",
                "High",
                "exchange/source candle close disagreement detected",
                AFFECTED_MODULES["candles"],
                sorted(affected_symbols),
                sorted(affected_timeframes),
                examples,
                "Add source-consensus or source-priority quarantine before model features consume disagreeing candles.",
            )
        )
    return findings


def check_multi_timeframe_alignment(
    candles: list[Candle], decisions: list[dict[str, Any]], args: argparse.Namespace
) -> tuple[list[Finding], dict[str, Any]]:
    findings: list[Finding] = []
    summary = {"decisions_checked": 0, "violations": []}
    if not decisions:
        findings.append(
            Finding(
                "mtf_alignment.no_decisions",
                "WARN",
                "High",
                "no decision records found for multi-timeframe alignment",
                AFFECTED_MODULES["mtf"],
                recommended_fix="Provide prediction/orchestrator/risk decision records with decision_time or generated_at fields.",
            )
        )
        return findings, summary
    if not candles:
        findings.append(
            Finding(
                "mtf_alignment.no_candles",
                "WARN",
                "High",
                "no candle records found for multi-timeframe alignment",
                AFFECTED_MODULES["mtf"],
                recommended_fix="Provide candle snapshots for every decision symbol/timeframe.",
            )
        )
        return findings, summary

    candles_by_symbol_tf: dict[tuple[str, str], list[Candle]] = defaultdict(list)
    for candle in candles:
        if candle.open_time is not None:
            candles_by_symbol_tf[(candle.symbol, candle.timeframe)].append(candle)
    for rows in candles_by_symbol_tf.values():
        rows.sort(key=lambda candle: normalize_ms(candle.open_time or 0))

    future_use: list[dict[str, Any]] = []
    unfinished_htf: list[dict[str, Any]] = []
    inconsistent_cutoffs: list[dict[str, Any]] = []
    checked = 0
    for decision in decisions:
        decision_time = first_timestamp(
            decision,
            ("decision_time", "decision_cutoff", "decision_cutoff_time", "generated_at", "generated_est", "timestamp"),
        )
        symbol = normalize_symbol(first_value(decision, ("symbol", "asset", "market")))
        if decision_time is None or symbol == "unknown":
            continue
        checked += 1
        latest_by_tf: dict[str, Candle | None] = {}
        close_times: list[int] = []
        for timeframe in REQUIRED_ALIGNMENT_TIMEFRAMES:
            rows = candles_by_symbol_tf.get((symbol, timeframe), [])
            latest = latest_candle_at_or_before(rows, decision_time)
            latest_by_tf[timeframe] = latest
            if latest is None:
                continue
            latest_close = candle_close_or_expected(latest)
            if latest_close is not None:
                close_times.append(normalize_ms(latest_close))
                if normalize_ms(latest_close) > normalize_ms(decision_time):
                    future_use.append(
                        {
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "decision_time": decision_time,
                            "candle_close_time": latest_close,
                            "decision": compact_record(decision),
                        }
                    )
            if timeframe in HIGHER_TIMEFRAMES and latest.final is False:
                unfinished_htf.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "decision_time": decision_time,
                        "candle": compact_record(latest.raw),
                    }
                )
        if close_times:
            max_close = max(close_times)
            min_close = min(close_times)
            if max_close > normalize_ms(decision_time) or max_close - min_close > TIMEFRAME_SECONDS["1h"] * 1000:
                inconsistent_cutoffs.append(
                    {
                        "symbol": symbol,
                        "decision_time": decision_time,
                        "latest_valid_candles": {
                            timeframe: candle_summary(latest_by_tf.get(timeframe))
                            for timeframe in REQUIRED_ALIGNMENT_TIMEFRAMES
                        },
                    }
                )

    summary["decisions_checked"] = checked
    summary["violations"] = {
        "future_use": future_use[: args.max_examples],
        "unfinished_higher_tf": unfinished_htf[: args.max_examples],
        "inconsistent_cutoffs": inconsistent_cutoffs[: args.max_examples],
    }

    if future_use:
        findings.append(
            Finding(
                "mtf_alignment.future_candle_use",
                "FAIL",
                "Critical",
                "look-ahead leakage detected",
                AFFECTED_MODULES["mtf"],
                sorted({str(item["symbol"]) for item in future_use}),
                sorted({str(item["timeframe"]) for item in future_use}),
                future_use[: args.max_examples],
                "Reject any decision whose source candle close time is after decision_time.",
            )
        )
    if unfinished_htf:
        findings.append(
            Finding(
                "mtf_alignment.unfinished_higher_tf",
                "FAIL",
                "Critical",
                "unfinished higher-timeframe candle detected",
                AFFECTED_MODULES["mtf"],
                sorted({str(item["symbol"]) for item in unfinished_htf}),
                sorted({str(item["timeframe"]) for item in unfinished_htf}),
                unfinished_htf[: args.max_examples],
                "Require exchange close confirmation for all higher-timeframe candles before feature/prediction use.",
            )
        )
    if inconsistent_cutoffs:
        findings.append(
            Finding(
                "mtf_alignment.inconsistent_cutoffs",
                "FAIL",
                "High",
                "multi-timeframe candles use inconsistent cutoffs",
                AFFECTED_MODULES["mtf"],
                sorted({str(item["symbol"]) for item in inconsistent_cutoffs}),
                list(REQUIRED_ALIGNMENT_TIMEFRAMES),
                inconsistent_cutoffs[: args.max_examples],
                "Build decisions from an atomic market-state snapshot with one feature_cutoff shared by all timeframes.",
            )
        )
    if checked and not future_use and not unfinished_htf and not inconsistent_cutoffs:
        findings.append(
            Finding(
                "mtf_alignment.pass",
                "PASS",
                "Info",
                "multi-timeframe alignment checks passed for loaded decisions",
                AFFECTED_MODULES["mtf"],
                recommended_fix="No action for loaded records. Keep checking representative decision windows.",
            )
        )
    return findings, summary


def check_feature_integrity(features: list[dict[str, Any]], args: argparse.Namespace) -> tuple[list[Finding], dict[str, Any]]:
    findings: list[Finding] = []
    summary = {"feature_vectors_checked": len(features), "examples": []}
    if not features:
        findings.append(
            Finding(
                "feature_integrity.no_data",
                "WARN",
                "High",
                "no feature vectors found",
                AFFECTED_MODULES["features"],
                recommended_fix="Provide feature snapshot records such as v2:features:latest:* or JSON exports.",
            )
        )
        return findings, summary

    invalid_examples: list[dict[str, Any]] = []
    stale_examples: list[dict[str, Any]] = []
    future_examples: list[dict[str, Any]] = []
    forward_fill_examples: list[dict[str, Any]] = []
    signatures_by_context: dict[tuple[str, str], list[tuple[int, str, dict[str, Any]]]] = defaultdict(list)

    for feature in features:
        vector = extract_feature_vector(feature)
        invalid_count = count_invalid_values(vector)
        stale_count = stale_feature_count(feature)
        decision_time = first_timestamp(
            feature,
            ("decision_time", "decision_cutoff", "feature_cutoff", "generated_at", "generated_utc", "timestamp"),
        )
        source_times = source_candle_timestamps(feature)
        future_count = 0
        if decision_time is not None:
            future_count = sum(1 for source_time in source_times if normalize_ms(source_time) > normalize_ms(decision_time))
        feature_time = first_timestamp(feature, ("feature_timestamp", "generated_at", "generated_utc", "timestamp"))
        symbol = normalize_symbol(first_value(feature, ("symbol", "asset", "market")))
        timeframe = normalize_timeframe(first_value(feature, ("timeframe", "interval", "tf")))
        feature_hash = first_value(feature, ("feature_hash", "feature_snapshot_id", "tensor_id"))
        feature_version = first_value(feature, ("feature_version", "version"))
        summary["examples"].append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "feature_timestamp": feature_time,
                "source_candle_timestamps": source_times[: args.max_examples],
                "feature_version": feature_version,
                "feature_hash": feature_hash,
                "nan_inf_null_count": invalid_count,
                "stale_feature_count": stale_count,
                "future_feature_leakage_count": future_count,
            }
        )
        if len(summary["examples"]) > args.max_examples:
            summary["examples"] = summary["examples"][: args.max_examples]
        if invalid_count:
            invalid_examples.append({"invalid_count": invalid_count, "feature": compact_record(feature)})
        if stale_count:
            stale_examples.append({"stale_count": stale_count, "feature": compact_record(feature)})
        if future_count:
            future_examples.append({"future_count": future_count, "feature": compact_record(feature)})
        if feature_time is not None:
            signature = stable_hash(vector)
            signatures_by_context[(symbol, timeframe)].append((normalize_ms(feature_time), signature, feature))
        if explicit_forward_fill_flag(feature):
            forward_fill_examples.append({"feature": compact_record(feature), "reason": "explicit forward-fill/interpolation flag"})

    for (_symbol, _timeframe), rows in signatures_by_context.items():
        rows.sort(key=lambda item: item[0])
        for previous, current in zip(rows, rows[1:], strict=False):
            if previous[1] == current[1] and previous[0] != current[0]:
                forward_fill_examples.append(
                    {
                        "previous_time": previous[0],
                        "current_time": current[0],
                        "feature": compact_record(current[2]),
                        "reason": "identical feature vector across different timestamps",
                    }
                )
                break

    if invalid_examples:
        findings.append(
            Finding(
                "feature_integrity.invalid_values",
                "FAIL",
                "High",
                "NaN/inf/null feature values detected",
                AFFECTED_MODULES["features"],
                example_records=invalid_examples[: args.max_examples],
                recommended_fix="Reject invalid feature vectors before tensor construction or require explicit missing masks.",
            )
        )
    if stale_examples:
        findings.append(
            Finding(
                "feature_integrity.stale",
                "FAIL",
                "High",
                "stale feature vectors detected",
                AFFECTED_MODULES["features"],
                example_records=stale_examples[: args.max_examples],
                recommended_fix="Block stale feature vectors before prediction/training and preserve source freshness timestamps.",
            )
        )
    if future_examples:
        findings.append(
            Finding(
                "feature_integrity.future_use",
                "FAIL",
                "Critical",
                "future feature use detected",
                AFFECTED_MODULES["features"],
                example_records=future_examples[: args.max_examples],
                recommended_fix="Require source candle timestamps to be <= feature_cutoff/decision_time for every feature vector.",
            )
        )
    if forward_fill_examples:
        findings.append(
            Finding(
                "feature_integrity.forward_fill_possible",
                "FAIL",
                "Medium",
                "silent forward-fill or interpolation suspected",
                AFFECTED_MODULES["features"],
                example_records=forward_fill_examples[: args.max_examples],
                recommended_fix="Emit explicit forward_fill/interpolated flags and quarantine those features for trusted training.",
            )
        )
    if not any(f.check_id.startswith("feature_integrity.") and f.status == "FAIL" for f in findings):
        findings.append(
            Finding(
                "feature_integrity.pass",
                "PASS",
                "Info",
                "feature integrity checks passed for loaded vectors",
                AFFECTED_MODULES["features"],
                recommended_fix="No action for loaded records. Keep checking source timestamps and invalid values.",
            )
        )
    return findings, summary


def check_masa_ppo_consistency(decisions: list[dict[str, Any]], args: argparse.Namespace) -> tuple[list[Finding], dict[str, Any]]:
    findings: list[Finding] = []
    summary = {"decisions_checked": len(decisions), "examples": []}
    if not decisions:
        findings.append(
            Finding(
                "masa_ppo.no_decisions",
                "WARN",
                "High",
                "no model decision records found for MASA/PPO consistency",
                AFFECTED_MODULES["masa_ppo"],
                recommended_fix="Provide prediction records containing MASA and PPO metadata.",
            )
        )
        return findings, summary

    missing_contract: list[dict[str, Any]] = []
    masa_future: list[dict[str, Any]] = []
    ppo_future: list[dict[str, Any]] = []
    context_mismatch: list[dict[str, Any]] = []
    cutoff_mismatch: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []

    for decision in decisions:
        decision_time = first_timestamp(decision, ("decision_time", "decision_cutoff", "generated_at", "generated_est", "timestamp"))
        masa_generated_at = first_timestamp(decision, ("masa_generated_at", "masa_generated_utc"))
        masa_feature_cutoff = first_timestamp(decision, ("masa_feature_cutoff", "masa_cutoff", "masa_input_cutoff"))
        masa_forecast_horizon = first_value(decision, ("masa_forecast_horizon", "forecast_horizon"))
        ppo_observation_time = first_timestamp(decision, ("ppo_observation_time", "observation_time"))
        ppo_feature_cutoff = first_timestamp(decision, ("ppo_feature_cutoff", "feature_cutoff", "decision_cutoff"))
        symbol = normalize_symbol(first_value(decision, ("symbol", "asset", "market")))
        timeframe = normalize_timeframe(first_value(decision, ("timeframe", "interval", "tf")))
        masa_symbol = normalize_symbol(first_value(decision, ("masa_symbol", "masa_asset", "symbol")))
        ppo_symbol = normalize_symbol(first_value(decision, ("ppo_symbol", "ppo_asset", "symbol")))
        masa_timeframe = normalize_timeframe(first_value(decision, ("masa_timeframe", "timeframe")))
        ppo_timeframe = normalize_timeframe(first_value(decision, ("ppo_timeframe", "timeframe")))

        example = {
            "symbol": symbol,
            "timeframe": timeframe,
            "decision_time": decision_time,
            "masa_generated_at": masa_generated_at,
            "masa_feature_cutoff": masa_feature_cutoff,
            "masa_forecast_horizon": masa_forecast_horizon,
            "ppo_observation_time": ppo_observation_time,
            "ppo_feature_cutoff": ppo_feature_cutoff,
        }
        if len(summary["examples"]) < args.max_examples:
            summary["examples"].append(example)

        required_missing = [
            name
            for name, value in {
                "masa_generated_at": masa_generated_at,
                "masa_feature_cutoff": masa_feature_cutoff,
                "masa_forecast_horizon": masa_forecast_horizon,
                "ppo_observation_time": ppo_observation_time,
                "ppo_feature_cutoff": ppo_feature_cutoff,
            }.items()
            if value is None
        ]
        if required_missing:
            missing_contract.append({"missing": required_missing, "decision": compact_record(decision)})
        if decision_time is not None and masa_feature_cutoff is not None and normalize_ms(masa_feature_cutoff) > normalize_ms(decision_time):
            masa_future.append({"decision": compact_record(decision), "masa_feature_cutoff": masa_feature_cutoff, "decision_time": decision_time})
        if decision_time is not None and ppo_feature_cutoff is not None and normalize_ms(ppo_feature_cutoff) > normalize_ms(decision_time):
            ppo_future.append({"decision": compact_record(decision), "ppo_feature_cutoff": ppo_feature_cutoff, "decision_time": decision_time})
        if (
            masa_feature_cutoff is not None
            and ppo_feature_cutoff is not None
            and normalize_ms(masa_feature_cutoff) != normalize_ms(ppo_feature_cutoff)
        ):
            cutoff_mismatch.append(
                {
                    "decision": compact_record(decision),
                    "masa_feature_cutoff": masa_feature_cutoff,
                    "ppo_feature_cutoff": ppo_feature_cutoff,
                }
            )
        if symbol != "unknown" and (masa_symbol != symbol or ppo_symbol != symbol or masa_timeframe != timeframe or ppo_timeframe != timeframe):
            context_mismatch.append({"decision": compact_record(decision), "symbol": symbol, "masa_symbol": masa_symbol, "ppo_symbol": ppo_symbol})

        masa_direction = directional_opinion(first_value(decision, ("masa_direction", "masa_signal", "masa_score")))
        ppo_direction = ppo_directional_opinion(decision)
        if masa_direction and ppo_direction and masa_direction != ppo_direction:
            disagreements.append({"decision": compact_record(decision), "masa_direction": masa_direction, "ppo_direction": ppo_direction})

    if missing_contract:
        findings.append(
            Finding(
                "masa_ppo.missing_contract",
                "FAIL",
                "High",
                "MASA/PPO contract fields missing",
                AFFECTED_MODULES["masa_ppo"],
                example_records=missing_contract[: args.max_examples],
                recommended_fix="Add generated_at, feature_cutoff, forecast_horizon, observation_time, observation hash, policy version, and MASA id fields.",
            )
        )
    if masa_future:
        findings.append(
            Finding(
                "masa_ppo.masa_future_cutoff",
                "FAIL",
                "Critical",
                "look-ahead leakage detected",
                AFFECTED_MODULES["masa_ppo"],
                example_records=masa_future[: args.max_examples],
                recommended_fix="Reject MASA predictions whose feature_cutoff is after PPO decision_time.",
            )
        )
    if ppo_future:
        findings.append(
            Finding(
                "masa_ppo.ppo_future_cutoff",
                "FAIL",
                "Critical",
                "future feature use detected",
                AFFECTED_MODULES["masa_ppo"],
                example_records=ppo_future[: args.max_examples],
                recommended_fix="Reject PPO observations whose feature_cutoff is after decision_time.",
            )
        )
    if context_mismatch:
        findings.append(
            Finding(
                "masa_ppo.context_mismatch",
                "FAIL",
                "High",
                "MASA and PPO context mismatch detected",
                AFFECTED_MODULES["masa_ppo"],
                example_records=context_mismatch[: args.max_examples],
                recommended_fix="Require matching symbol, exchange, timeframe, feature_cutoff, and input hash between MASA and PPO.",
            )
        )
    if cutoff_mismatch:
        findings.append(
            Finding(
                "masa_ppo.cutoff_mismatch",
                "FAIL",
                "Critical",
                "MASA/PPO cutoff mismatch detected",
                AFFECTED_MODULES["masa_ppo"],
                example_records=cutoff_mismatch[: args.max_examples],
                recommended_fix="Require MASA and PPO to share the same market-state cutoff and input hash before a decision can train or execute.",
            )
        )
    if disagreements:
        findings.append(
            Finding(
                "masa_ppo.directional_disagreement",
                "FAIL",
                "Medium",
                "MASA/PPO directional disagreement detected",
                AFFECTED_MODULES["masa_ppo"],
                example_records=disagreements[: args.max_examples],
                recommended_fix="Log disagreement with both input hashes and decide whether disagreement blocks, reduces, or only annotates trades.",
            )
        )
    if not any(f.check_id.startswith("masa_ppo.") and f.status == "FAIL" for f in findings):
        findings.append(
            Finding(
                "masa_ppo.pass",
                "PASS",
                "Info",
                "MASA/PPO consistency checks passed for loaded decisions",
                AFFECTED_MODULES["masa_ppo"],
                recommended_fix="No action for loaded records. Keep enforcing explicit contract fields.",
            )
        )
    return findings, summary


def check_training_samples(samples: list[dict[str, Any]], args: argparse.Namespace) -> tuple[list[Finding], dict[str, Any]]:
    findings: list[Finding] = []
    summary = {"samples_checked": len(samples), "examples": []}
    if not samples:
        findings.append(
            Finding(
                "training_samples.no_data",
                "WARN",
                "High",
                "no training sample records found",
                AFFECTED_MODULES["training"],
                recommended_fix="Provide trainer dataset/sample manifests or JSON exports with sample-level cutoffs and labels.",
            )
        )
        return findings, summary

    future_label_examples: list[dict[str, Any]] = []
    backfill_examples: list[dict[str, Any]] = []
    missing_cost_examples: list[dict[str, Any]] = []
    missing_execution_examples: list[dict[str, Any]] = []
    dirty_accepted_examples: list[dict[str, Any]] = []
    rejected_positive_examples: list[dict[str, Any]] = []

    for sample in samples:
        feature_cutoff = first_timestamp(sample, ("feature_cutoff", "decision_cutoff", "observation_time", "generated_at"))
        label_start = first_timestamp(sample, ("label_start_time", "label_start", "horizon_start"))
        label_end = first_timestamp(sample, ("label_end_time", "label_end", "horizon_end"))
        horizon_seconds = numeric_value(first_value(sample, ("prediction_horizon_seconds", "forecast_horizon_seconds", "horizon_seconds")))
        accepted = truthy(first_value(sample, ("used_for_training", "accepted", "trainer_consumable", "included_in_training")))
        classification = str(first_value(sample, ("row_classification", "sample_classification", "classification")) or "").upper()
        dirty_flags = collect_dirty_training_flags(sample, classification)
        has_fees = first_value(sample, ("fee_bps", "fees", "fee", "taker_fee_bps")) is not None
        has_slippage = first_value(sample, ("slippage_bps", "slippage")) is not None
        requires_execution = truthy(first_value(sample, ("requires_execution_result", "execution_required")))
        execution_available = first_value(sample, ("execution_result", "fill_status", "order_status", "paper_fill")) is not None
        backfilled = truthy(first_value(sample, ("backfilled", "is_backfill", "source_backfilled", "backfill")))
        order_status = str(first_value(sample, ("fill_status", "order_status", "execution_status")) or "").lower()
        positive_training_sample = truthy(first_value(sample, ("positive_training_sample", "execution_success", "filled", "fill_success")))
        if not positive_training_sample:
            sample_action = str(first_value(sample, ("label_action", "selected_action", "requested_action")) or "").lower()
            positive_training_sample = sample_action not in {"", "hold", "abstain", "none", "no_trade"}

        if len(summary["examples"]) < args.max_examples:
            summary["examples"].append(
                {
                    "feature_cutoff": feature_cutoff,
                    "label_start_time": label_start,
                    "label_end_time": label_end,
                    "prediction_horizon_seconds": horizon_seconds,
                    "uses_backfilled_data": backfilled,
                    "has_fees": has_fees,
                    "has_slippage": has_slippage,
                    "execution_result_available": execution_available,
                    "accepted": accepted,
                    "dirty_flags": dirty_flags,
                }
            )

        if label_start is not None and label_end is not None and horizon_seconds is not None:
            actual_seconds = (normalize_ms(label_end) - normalize_ms(label_start)) / 1000.0
            if actual_seconds > horizon_seconds + 1:
                future_label_examples.append({"sample": compact_record(sample), "actual_label_seconds": actual_seconds, "horizon_seconds": horizon_seconds})
        if backfilled and accepted:
            backfill_examples.append({"sample": compact_record(sample)})
        if accepted and (not has_fees or not has_slippage):
            missing_cost_examples.append({"sample": compact_record(sample), "has_fees": has_fees, "has_slippage": has_slippage})
        if accepted and requires_execution and not execution_available:
            missing_execution_examples.append({"sample": compact_record(sample)})
        if accepted and dirty_flags:
            dirty_accepted_examples.append({"sample": compact_record(sample), "dirty_flags": dirty_flags})
        if accepted and order_status in {"rejected", "canceled", "cancelled", "expired"} and positive_training_sample:
            rejected_positive_examples.append({"sample": compact_record(sample), "order_status": order_status})

    if future_label_examples:
        findings.append(
            Finding(
                "training_samples.future_label_leakage",
                "FAIL",
                "Critical",
                "look-ahead leakage detected",
                AFFECTED_MODULES["training"],
                example_records=future_label_examples[: args.max_examples],
                recommended_fix="Reject labels whose end time exceeds the declared prediction horizon.",
            )
        )
    if backfill_examples:
        findings.append(
            Finding(
                "training_samples.backfilled_accepted",
                "FAIL",
                "Critical",
                "dirty training sample accepted",
                AFFECTED_MODULES["training"],
                example_records=backfill_examples[: args.max_examples],
                recommended_fix="Quarantine backfilled samples from live-style training unless explicitly marked and isolated.",
            )
        )
    if dirty_accepted_examples:
        findings.append(
            Finding(
                "training_samples.dirty_accepted",
                "FAIL",
                "Critical",
                "dirty training sample accepted",
                AFFECTED_MODULES["training"],
                example_records=dirty_accepted_examples[: args.max_examples],
                recommended_fix="Require TRAINABLE classification plus PIT, freshness, finality, fee/slippage, and position-state checks before training.",
            )
        )
    if missing_cost_examples:
        findings.append(
            Finding(
                "training_samples.missing_costs",
                "FAIL",
                "High",
                "accepted training samples missing fees or slippage",
                AFFECTED_MODULES["training"],
                example_records=missing_cost_examples[: args.max_examples],
                recommended_fix="Require explicit fee and slippage provenance for all non-hold training samples.",
            )
        )
    if missing_execution_examples:
        findings.append(
            Finding(
                "training_samples.missing_execution_result",
                "FAIL",
                "High",
                "accepted training samples missing required execution result",
                AFFECTED_MODULES["training"],
                example_records=missing_execution_examples[: args.max_examples],
                recommended_fix="Attach fill/reject/cancel outcome before a sample enters execution-feedback training.",
            )
        )
    if rejected_positive_examples:
        findings.append(
            Finding(
                "training_samples.rejected_order_positive",
                "FAIL",
                "Critical",
                "dirty training sample accepted",
                AFFECTED_MODULES["training"],
                example_records=rejected_positive_examples[: args.max_examples],
                recommended_fix="Do not create positive execution-training samples from rejected, canceled, expired, or unfilled orders.",
            )
        )
    if not any(f.check_id.startswith("training_samples.") and f.status == "FAIL" for f in findings):
        findings.append(
            Finding(
                "training_samples.pass",
                "PASS",
                "Info",
                "training sample checks passed for loaded samples",
                AFFECTED_MODULES["training"],
                recommended_fix="No action for loaded records. Keep checking representative training batches.",
            )
        )
    return findings, summary


def check_trust_schema_required_fields(
    records: list[SourceRecord],
    args: argparse.Namespace,
) -> list[Finding]:
    """Check all records with trust_schema_version for required temporal fields."""
    findings: list[Finding] = []
    missing_available_at: list[dict[str, Any]] = []
    missing_feature_cutoff: list[dict[str, Any]] = []

    for record in records:
        for item in iter_candidate_items(record.value):
            if not isinstance(item, dict):
                continue
            if not item.get("trust_schema_version"):
                continue
            if "available_at" in item and item["available_at"] is None:
                missing_available_at.append({"source": record.source, "record": compact_record(item)})
            if "feature_cutoff" in item and item["feature_cutoff"] is None:
                missing_feature_cutoff.append({"source": record.source, "record": compact_record(item)})

    if missing_available_at:
        findings.append(
            Finding(
                "feature_integrity.missing_available_at",
                "FAIL",
                "Critical",
                "feature vectors missing available_at timestamp detected",
                AFFECTED_MODULES["features"],
                example_records=missing_available_at[: args.max_examples],
                recommended_fix="Set available_at on every trust-schema record to enforce temporal ordering and freshness guarantees.",
            )
        )
    if missing_feature_cutoff:
        findings.append(
            Finding(
                "feature_integrity.missing_feature_cutoff",
                "FAIL",
                "Critical",
                "feature vectors missing feature_cutoff timestamp detected",
                AFFECTED_MODULES["features"],
                example_records=missing_feature_cutoff[: args.max_examples],
                recommended_fix="Set feature_cutoff on every trust-schema record to enforce look-ahead leakage prevention.",
            )
        )
    return findings


def _record_missing_replay_snapshot(record: dict[str, Any]) -> bool:
    replay_id = record.get("replay_snapshot_id")
    replay_write = record.get("replay_snapshot_write_success")
    if replay_id is None or replay_id == "" or replay_id is False:
        return True
    if replay_write is False:
        return True
    return False


def _record_missing_mtf_snapshot(record: dict[str, Any]) -> bool:
    mtf_id = record.get("mtf_snapshot_id")
    mtf_valid = record.get("mtf_snapshot_valid")
    if mtf_id is None or mtf_id == "" or mtf_id is False:
        return True
    if mtf_valid is False:
        return True
    return False


def _is_active_execution_record(record: dict[str, Any]) -> bool:
    active_flags = (
        "pre_trade_allowed", "paper_fill_allowed", "risk_eligible",
        "paper_eligible", "routes_to_orchestrator",
    )
    for flag in active_flags:
        if record.get(flag) is True:
            return True
    if str(record.get("risk_action") or "").lower() in {"allow", "approved"}:
        return True
    if str(record.get("risk_state") or "").upper() in {"APPROVED", "ALLOW"}:
        return True
    return False


def _is_terminal_inactive_execution_record(record: dict[str, Any]) -> bool:
    lifecycle = str(record.get("paper_lifecycle_status") or "").strip().upper()
    persistence = str(record.get("paper_fill_persistence_status") or "").strip().upper()
    terminal = {
        "CLOSED_PREVIOUSLY", "EXPIRED_PREVIOUSLY", "CANCELED_PREVIOUSLY",
        "CANCELLED_PREVIOUSLY", "REJECTED_PREVIOUSLY",
    }
    if lifecycle in terminal:
        return True
    return lifecycle == "CLOSED" and persistence in {
        "EXISTING_FILL_CARRIED_FORWARD", "HISTORICAL_FILL_CARRIED_FORWARD",
    }


def check_snapshot_contract(
    decisions: list[dict[str, Any]],
    execution_records: list[dict[str, Any]],
    args: argparse.Namespace,
) -> list[Finding]:
    findings: list[Finding] = []
    replay_missing_examples: list[dict[str, Any]] = []
    mtf_missing_examples: list[dict[str, Any]] = []
    trust_contract_examples: list[dict[str, Any]] = []

    for decision in decisions:
        if not decision.get("trust_schema_version"):
            continue
        if _record_missing_replay_snapshot(decision):
            replay_missing_examples.append({"source": "masa_ppo", "record": compact_record(decision)})
        if _record_missing_mtf_snapshot(decision):
            mtf_missing_examples.append({"source": "masa_ppo", "record": compact_record(decision)})

    for record in execution_records:
        if _is_terminal_inactive_execution_record(record):
            continue
        if not _is_active_execution_record(record):
            continue
        if _record_missing_replay_snapshot(record):
            replay_missing_examples.append({"source": "execution_record", "record": compact_record(record)})
        if _record_missing_mtf_snapshot(record):
            mtf_missing_examples.append({"source": "execution_record", "record": compact_record(record)})
        missing_trust_fields: list[str] = []
        if not record.get("trust_schema_version"):
            missing_trust_fields.append("trust_schema_version")
        if record.get("replay_snapshot_id") is None and record.get("trust_schema_version"):
            missing_trust_fields.append("replay_snapshot_id")
        if record.get("mtf_snapshot_id") is None and record.get("trust_schema_version"):
            missing_trust_fields.append("mtf_snapshot_id")
        if missing_trust_fields:
            trust_contract_examples.append({
                "missing_fields": missing_trust_fields,
                "record": compact_record(record),
            })

    if replay_missing_examples:
        findings.append(
            Finding(
                "replay_snapshot.missing",
                "FAIL",
                "Critical",
                "active records missing replay snapshot evidence",
                AFFECTED_MODULES.get("masa_ppo", []),
                example_records=replay_missing_examples[: args.max_examples],
                recommended_fix="Every active prediction/decision/paper-intent must have replay_snapshot_id and replay_snapshot_write_success=True.",
            )
        )
    if mtf_missing_examples:
        findings.append(
            Finding(
                "mtf_snapshot.missing",
                "FAIL",
                "Critical",
                "active records missing MTF snapshot metadata",
                AFFECTED_MODULES.get("mtf", []),
                example_records=mtf_missing_examples[: args.max_examples],
                recommended_fix="Every active prediction/decision/paper-intent must have mtf_snapshot_id and mtf_snapshot_valid=True.",
            )
        )
    if trust_contract_examples:
        findings.append(
            Finding(
                "runtime_trust.active_stale_missing_contract",
                "FAIL",
                "Critical",
                "active runtime records missing trust contract fields",
                AFFECTED_MODULES.get("masa_ppo", []),
                example_records=trust_contract_examples[: args.max_examples],
                recommended_fix="All active runtime records must carry trust_schema_version, replay_snapshot_id, and mtf_snapshot_id.",
            )
        )
    return findings


def check_execution_records(records: list[dict[str, Any]], args: argparse.Namespace) -> tuple[list[Finding], dict[str, Any]]:
    findings: list[Finding] = []
    summary = {"records_checked": len(records), "examples": []}
    if not records:
        findings.append(
            Finding(
                "execution.no_data",
                "WARN",
                "High",
                "no trade/order/decision execution records found",
                AFFECTED_MODULES["execution"],
                recommended_fix="Provide paper ledger, risk decision, live transport, or order records.",
            )
        )
        return findings, summary

    invalid_transition_examples: list[dict[str, Any]] = []
    partial_unhandled_examples: list[dict[str, Any]] = []
    rejected_changed_examples: list[dict[str, Any]] = []
    drift_examples: list[dict[str, Any]] = []

    for record in records:
        position_before = first_value(record, ("position_before", "before_position", "previous_position", "local_position_before"))
        requested_action = str(first_value(record, ("requested_action", "action", "risk_action", "order_action")) or "").lower()
        position_after = first_value(record, ("position_after", "after_position", "new_position", "local_position_after"))
        exchange_response = first_value(record, ("exchange_response", "exchange_result", "order_response"))
        fill_status = str(first_value(record, ("fill_status", "order_status", "status")) or "").lower()
        invalid_flag = truthy(first_value(record, ("invalid_transition", "transition_invalid")))
        local_position = first_value(record, ("local_position", "paper_position", "position_after"))
        exchange_position = first_value(record, ("exchange_position", "binance_position", "exchange_position_after"))
        if len(summary["examples"]) < args.max_examples:
            summary["examples"].append(
                {
                    "position_before": position_before,
                    "requested_action": requested_action,
                    "position_after": position_after,
                    "exchange_response": compact_record(exchange_response),
                    "fill_status": fill_status,
                    "partial_fill_handled": first_value(record, ("partial_fill_handled", "remaining_qty")) is not None,
                }
            )

        if invalid_flag or transition_is_invalid(position_before, requested_action, position_after):
            invalid_transition_examples.append({"record": compact_record(record)})
        if "partial" in fill_status and not truthy(first_value(record, ("partial_fill_handled",))) and first_value(record, ("remaining_qty", "remaining_quantity")) is None:
            partial_unhandled_examples.append({"record": compact_record(record)})
        if fill_status in {"rejected", "canceled", "cancelled", "expired"} and positions_differ(position_before, position_after):
            rejected_changed_examples.append({"record": compact_record(record)})
        if local_position is not None and exchange_position is not None and positions_differ(local_position, exchange_position):
            drift_examples.append({"record": compact_record(record), "local_position": local_position, "exchange_position": exchange_position})

    if invalid_transition_examples:
        findings.append(
            Finding(
                "execution.invalid_transition",
                "FAIL",
                "Critical",
                "invalid position transition detected",
                AFFECTED_MODULES["execution"],
                example_records=invalid_transition_examples[: args.max_examples],
                recommended_fix="Add a pre-submit state machine for open/close/flip/hedge/reduce-only transitions using exchange and local position state.",
            )
        )
    if rejected_changed_examples:
        findings.append(
            Finding(
                "execution.rejected_changed_position",
                "FAIL",
                "Critical",
                "invalid position transition detected",
                AFFECTED_MODULES["execution"],
                example_records=rejected_changed_examples[: args.max_examples],
                recommended_fix="Do not update local position state for rejected, canceled, expired, or unfilled orders.",
            )
        )
    if partial_unhandled_examples:
        findings.append(
            Finding(
                "execution.partial_unhandled",
                "FAIL",
                "High",
                "partial fill handling missing",
                AFFECTED_MODULES["execution"],
                example_records=partial_unhandled_examples[: args.max_examples],
                recommended_fix="Persist partial-fill quantity, remaining quantity, average price, fees, and follow-up reconciliation state.",
            )
        )
    if drift_examples:
        findings.append(
            Finding(
                "execution.position_drift",
                "FAIL",
                "Critical",
                "local and exchange position state mismatch detected",
                AFFECTED_MODULES["execution"],
                example_records=drift_examples[: args.max_examples],
                recommended_fix="Reconcile local and exchange position state before every live submit and after every fill lifecycle event.",
            )
        )
    if not any(f.check_id.startswith("execution.") and f.status == "FAIL" for f in findings):
        findings.append(
            Finding(
                "execution.pass",
                "PASS",
                "Info",
                "position/execution checks passed for loaded records",
                AFFECTED_MODULES["execution"],
                recommended_fix="No action for loaded records. Keep checking live/paper order lifecycle records.",
            )
        )
    return findings, summary


def check_config_records(records: list[dict[str, Any]], args: argparse.Namespace) -> tuple[list[Finding], dict[str, Any]]:
    findings: list[Finding] = []
    summary = {"records_checked": len(records), "examples": []}
    if not records:
        findings.append(
            Finding(
                "config.no_data",
                "WARN",
                "High",
                "no config/admin records found",
                AFFECTED_MODULES["config"],
                recommended_fix="Provide config-admin status payloads so staged dangerous settings, approvals, secrets, and mutation flags can be audited.",
            )
        )
        return findings, summary

    secret_examples: list[dict[str, Any]] = []
    approval_examples: list[dict[str, Any]] = []
    mutation_examples: list[dict[str, Any]] = []
    pending_examples: list[dict[str, Any]] = []
    live_gate_examples: list[dict[str, Any]] = []

    for record in records:
        live_gate = str(first_value(record, ("live_gate", "current_gate_state", "live_gate_state")) or "").lower()
        dangerous_pending = first_value(record, ("dangerous_settings_pending_approval", "pending_dangerous_settings"))
        secrets_written = truthy(first_value(record, ("secrets_written_to_payload", "secret_written", "secrets_exposed")))
        approval_created = truthy(first_value(record, ("approval_token_created", "approval_token_self_creatable", "self_approved")))
        old_redis_write = truthy(first_value(record, ("old_redis_write", "legacy_redis_write")))
        exchange_action = truthy(first_value(record, ("exchange_action_taken", "order_submitted", "live_order_submitted")))
        leverage_or_margin = truthy(first_value(record, ("leverage_or_margin_change", "margin_changed", "leverage_changed")))
        if len(summary["examples"]) < args.max_examples:
            summary["examples"].append(
                {
                    "live_gate": live_gate,
                    "dangerous_settings_pending_approval": dangerous_pending,
                    "secrets_written_to_payload": secrets_written,
                    "approval_token_created_or_self_creatable": approval_created,
                    "old_redis_write": old_redis_write,
                    "exchange_action_taken": exchange_action,
                    "leverage_or_margin_change": leverage_or_margin,
                    "record": compact_record(record),
                }
            )
        if secrets_written:
            secret_examples.append({"record": compact_record(record)})
        if approval_created:
            approval_examples.append({"record": compact_record(record)})
        if old_redis_write or exchange_action or leverage_or_margin:
            mutation_examples.append(
                {
                    "record": compact_record(record),
                    "old_redis_write": old_redis_write,
                    "exchange_action_taken": exchange_action,
                    "leverage_or_margin_change": leverage_or_margin,
                }
            )
        if has_pending_items(dangerous_pending):
            pending_examples.append({"record": compact_record(record), "pending": dangerous_pending})
        if live_gate and live_gate not in {"blocked_human_only", "disabled", "paper_only", "read_only"}:
            live_gate_examples.append({"record": compact_record(record), "live_gate": live_gate})

    if secret_examples:
        findings.append(
            Finding(
                "config.secrets_in_payload",
                "FAIL",
                "Critical",
                "config/admin payload contains secret leakage marker",
                AFFECTED_MODULES["config"],
                example_records=secret_examples[: args.max_examples],
                recommended_fix="Never write raw secrets into public/runtime payloads; emit only redacted fingerprints or boolean readiness fields.",
            )
        )
    if approval_examples:
        findings.append(
            Finding(
                "config.self_approval",
                "FAIL",
                "Critical",
                "config/admin approval token self-creation detected",
                AFFECTED_MODULES["config"],
                example_records=approval_examples[: args.max_examples],
                recommended_fix="Require external human approval for dangerous settings and forbid workers from creating approval tokens.",
            )
        )
    if mutation_examples:
        findings.append(
            Finding(
                "config.mutation_marker",
                "FAIL",
                "Critical",
                "config/admin mutation marker detected",
                AFFECTED_MODULES["config"],
                example_records=mutation_examples[: args.max_examples],
                recommended_fix="Keep config-admin workers read-only/fail-closed for exchange action, leverage, margin, and old Redis writes.",
            )
        )
    if pending_examples:
        findings.append(
            Finding(
                "config.dangerous_settings_pending",
                "FAIL",
                "High",
                "dangerous config settings pending approval",
                AFFECTED_MODULES["config"],
                example_records=pending_examples[: args.max_examples],
                recommended_fix="Keep dangerous settings staged and blocked until an external approval process records the decision.",
            )
        )
    if live_gate_examples:
        findings.append(
            Finding(
                "config.live_gate_not_blocked",
                "FAIL",
                "High",
                "config/admin live gate is not fail-closed",
                AFFECTED_MODULES["config"],
                example_records=live_gate_examples[: args.max_examples],
                recommended_fix="Keep config-admin status fail-closed unless separate operator-approved live readiness evidence is present.",
            )
        )
    if not any(f.check_id.startswith("config.") and f.status == "FAIL" for f in findings):
        findings.append(
            Finding(
                "config.pass",
                "PASS",
                "Info",
                "config/admin checks passed for loaded records",
                AFFECTED_MODULES["config"],
                recommended_fix="No action for loaded records. Keep config-admin safety fields in generated evidence.",
            )
        )
    return findings, summary


def check_live_vs_backtest_parity(records: list[SourceRecord], args: argparse.Namespace) -> tuple[list[Finding], dict[str, Any]]:
    _ = records, args
    differences = [
        {
            "area": "fees",
            "live": "exchange fill fees not fully reconciled by verifier unless provided in records",
            "paper": "deterministic/default bps fields are expected",
            "backtest": "paper projection or edge-proof defaults",
            "severity": "High",
            "recommended_fix": "Use one cost model contract with actual fill fee override when live data exists.",
        },
        {
            "area": "slippage_latency_spread",
            "live": "real market order slippage, latency, and spread",
            "paper": "deterministic assumptions",
            "backtest": "post-hoc/default assumptions",
            "severity": "High",
            "recommended_fix": "Record and replay bid/ask, latency, and fill price assumptions per decision.",
        },
        {
            "area": "candle_finality",
            "live": "trusts upstream finality metadata",
            "paper": "trusts upstream finality metadata",
            "backtest": "may use corrected/post-hoc candles unless source snapshots are supplied",
            "severity": "High",
            "recommended_fix": "Replay from immutable source snapshots with closed-candle proof.",
        },
        {
            "area": "order_fill_assumptions",
            "live": "exchange lifecycle and partial fills required",
            "paper": "immediate simulated fills",
            "backtest": "ledger projection/post-hoc fills",
            "severity": "High",
            "recommended_fix": "Use a shared order lifecycle model and mark assumptions by mode.",
        },
        {
            "area": "liquidation_funding_position_transitions",
            "live": "exchange state is authoritative",
            "paper": "local state and simplified costs",
            "backtest": "projection from paper/replay records",
            "severity": "Medium",
            "recommended_fix": "Persist funding, liquidation distance, margin mode, hedge mode, and transition state in every mode.",
        },
    ]
    finding = Finding(
        "parity.known_differences",
        "FAIL",
        "High",
        "live, paper, and backtest parity differences detected",
        AFFECTED_MODULES["parity"],
        example_records=differences,
        recommended_fix="Create one explicit execution-assumption contract consumed by live, paper, replay, training, and reporting.",
    )
    return [finding], {"differences": differences}


def promote_unknowns_to_critical(findings: list[Finding]) -> None:
    for finding in findings:
        if finding.status == "WARN" and finding.severity == "High":
            finding.status = "FAIL"
            finding.severity = "Critical"
            finding.title = f"strict unknown: {finding.title}"


def write_reports(report: TrustReport, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "pipeline_trust_report.json"
    md_path = output_dir / "pipeline_trust_report.md"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(report.to_jsonable(), handle, indent=2, sort_keys=True)
        handle.write("\n")
    with md_path.open("w", encoding="utf-8") as handle:
        handle.write(render_markdown(report))


def render_markdown(report: TrustReport) -> str:
    data = report.to_jsonable()
    summary = data["summary"]
    lines = [
        "# Pipeline Trust Verification Report",
        "",
        f"Generated UTC: `{report.generated_at}`",
        f"Mode: `{report.mode}`",
        f"Data sources: `{len(report.data_sources)}`",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|---|---:|",
        f"| Total findings | {summary['total_findings']} |",
        f"| Critical failures | {summary['critical_failures']} |",
        f"| Failures | {summary['failures']} |",
        f"| Warnings | {summary['warnings']} |",
        f"| Passes | {summary['passes']} |",
        "",
        "## Findings",
        "",
        "| Status | Severity | Check | Title | Affected modules | Recommended fix |",
        "|---|---|---|---|---|---|",
    ]
    for finding in report.findings:
        modules = "<br>".join(finding.affected_modules)
        lines.append(
            "| {status} | {severity} | `{check}` | {title} | {modules} | {fix} |".format(
                status=finding.status,
                severity=finding.severity,
                check=finding.check_id,
                title=escape_md(finding.title),
                modules=escape_md(modules),
                fix=escape_md(finding.recommended_fix),
            )
        )
    lines.extend(["", "## Example records", ""])
    for finding in report.findings:
        if not finding.example_records:
            continue
        lines.extend([f"### `{finding.check_id}`", "", "```json"])
        lines.append(json.dumps(finding.example_records, indent=2, sort_keys=True, default=str))
        lines.extend(["```", ""])
    lines.extend(["## Section summaries", "", "```json"])
    lines.append(json.dumps(report.summaries, indent=2, sort_keys=True, default=str))
    lines.extend(["```", ""])
    return "\n".join(lines)


def extract_candles(records: list[SourceRecord]) -> list[Candle]:
    candles: list[Candle] = []
    for record in records:
        for item in iter_candidate_items(record.value):
            if looks_like_candle(item, record.key):
                candle = parse_candle(record, item)
                if candle:
                    candles.append(candle)
        if isinstance(record.value, dict):
            for key in ("candles", "ohlcv", "klines", "rows"):
                child = record.value.get(key)
                if isinstance(child, list):
                    for item in child:
                        if looks_like_candle(item, record.key or key):
                            candle = parse_candle(record, item, parent=record.value)
                            if candle:
                                candles.append(candle)
    return candles


def extract_features(records: list[SourceRecord]) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for record in records:
        for item in iter_candidate_items(record.value):
            if looks_like_feature(item, record.key):
                features.append(with_source(item, record))
    return features


def extract_decisions(records: list[SourceRecord]) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for record in records:
        for item in iter_candidate_items(record.value):
            if looks_like_decision(item, record.key):
                decisions.append(with_source(item, record))
    return decisions


def extract_training_samples(records: list[SourceRecord]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for record in records:
        for item in iter_candidate_items(record.value):
            if looks_like_training_sample(item, record.key):
                samples.append(with_source(item, record))
    return samples


def extract_execution_records(records: list[SourceRecord]) -> list[dict[str, Any]]:
    execution_records: list[dict[str, Any]] = []
    for record in records:
        for item in iter_candidate_items(record.value):
            if looks_like_execution(item, record.key):
                execution_records.append(with_source(item, record))
    return execution_records


def extract_config_records(records: list[SourceRecord]) -> list[dict[str, Any]]:
    config_records: list[dict[str, Any]] = []
    for record in records:
        for item in iter_candidate_items(record.value):
            if looks_like_config(item, record.key):
                config_records.append(with_source(item, record))
    return config_records


def iter_candidate_items(value: Any) -> Iterable[Any]:
    if isinstance(value, list):
        for item in value:
            yield item
            if isinstance(item, dict):
                for child_key in ("payload", "record", "data", "value"):
                    child = item.get(child_key)
                    if isinstance(child, (dict, list)):
                        yield from iter_candidate_items(child)
    elif isinstance(value, dict):
        yield value
        for key in ("payload", "record", "data", "value", "latest", "snapshot", "decision", "sample"):
            child = value.get(key)
            if isinstance(child, (dict, list)):
                yield from iter_candidate_items(child)


def looks_like_candle(item: Any, key: str | None) -> bool:
    if isinstance(item, list) and len(item) >= 6:
        return bool(key and any(token in key.lower() for token in ("ohlcv", "kline", "candle")))
    if not isinstance(item, dict):
        return False
    lowered_key = (key or "").lower()
    candle_tokens = {"open", "high", "low", "close"}
    has_ohlc = candle_tokens.issubset({str(k).lower() for k in item})
    has_time = any(k in item for k in ("open_time", "ts", "timestamp", "candle_open_time", "time_period_start", "t"))
    return has_ohlc and (has_time or any(token in lowered_key for token in ("ohlcv", "kline", "candle")))


def looks_like_feature(item: Any, key: str | None) -> bool:
    if not isinstance(item, dict):
        return False
    lowered_key = (key or "").lower()
    if looks_like_training_sample(item, key) or looks_like_decision(item, key) or looks_like_config(item, key):
        return False
    if "features" in item and isinstance(item.get("features"), dict):
        return True
    if any(token in lowered_key for token in ("features", "technical_analysis", "unified_features")):
        return any(isinstance(value, (int, float, str, type(None), dict, list)) for value in item.values())
    return "feature_snapshot_id" in item or "feature_hash" in item


def is_model_prediction_record(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if "value" in item and {"redis_key", "category"}.intersection(item):
        return False
    if looks_like_training_sample(item, None):
        return False
    if not first_value(item, ("prediction_id", "decision_id")):
        return False
    model_fields = {
        "selected_action",
        "action_probabilities",
        "masa_signal",
        "masa_generated_at",
        "masa_feature_cutoff",
        "masa_forecast_horizon",
        "ppo_observation_time",
        "ppo_feature_cutoff",
    }
    return bool(model_fields.intersection(item))


def requires_snapshot_evidence(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if "value" in item and {"redis_key", "category"}.intersection(item):
        return False
    if looks_like_training_sample(item, None):
        return False
    if is_model_prediction_record(item):
        return True
    if item.get("trust_schema_version") and first_value(item, ("prediction_id", "decision_id")):
        return True
    active_flags = (
        "pre_trade_allowed",
        "paper_fill_allowed",
        "risk_eligible",
        "paper_eligible",
        "routes_to_orchestrator",
        "routeability_candidate",
    )
    return any(item.get(flag) is True for flag in active_flags)


def looks_like_decision(item: Any, key: str | None) -> bool:
    if not isinstance(item, dict):
        return False
    if "value" in item and {"redis_key", "category"}.intersection(item):
        return False
    if looks_like_training_sample(item, key):
        return False
    lowered_key = (key or "").lower()
    decision_keys = {
        "prediction_id",
        "selected_action",
        "action_probabilities",
        "masa_signal",
        "ppo_feature_cutoff",
        "risk_action",
        "orchestrator_action",
    }
    if decision_keys.intersection(item):
        return True
    return any(token in lowered_key for token in ("prediction", "decision", "signals:paper", "orchestrator", "risk")) and isinstance(item, dict)


def looks_like_training_sample(item: Any, key: str | None) -> bool:
    if not isinstance(item, dict):
        return False
    lowered_key = (key or "").lower()
    if "features" in item and isinstance(item.get("features"), dict) and "sample_id" not in item:
        return False
    sample_keys = {
        "training_sample_id",
        "sample_id",
        "row_classification",
        "label_start_time",
        "label_end_time",
        "used_for_training",
        "trainer_consumable",
    }
    return bool(sample_keys.intersection(item)) or "trainer" in lowered_key and "sample" in lowered_key


def looks_like_execution(item: Any, key: str | None) -> bool:
    if not isinstance(item, dict):
        return False
    lowered_key = (key or "").lower()
    execution_keys = {
        "position_before",
        "position_after",
        "requested_action",
        "fill_status",
        "order_status",
        "exchange_response",
        "order_id",
        "client_order_id",
        "local_position",
        "exchange_position",
    }
    if execution_keys.intersection(item):
        return True
    return any(token in lowered_key for token in ("paper:ledger", "paper:intents", "live_order", "execution", "order"))


def looks_like_config(item: Any, key: str | None) -> bool:
    if not isinstance(item, dict):
        return False
    lowered_key = (key or "").lower()
    config_keys = {
        "dangerous_settings_pending_approval",
        "secrets_written_to_payload",
        "approval_token_created",
        "approval_token_self_creatable",
        "old_redis_write",
        "exchange_action_taken",
        "leverage_or_margin_change",
        "settings_by_risk_class",
    }
    return bool(config_keys.intersection(item)) or any(
        token in lowered_key for token in ("config", "settings", "operator_runtime")
    )


def parse_candle(record: SourceRecord, item: Any, parent: dict[str, Any] | None = None) -> Candle | None:
    parent = parent or {}
    if isinstance(item, list):
        raw = {"row": item}
        symbol, exchange, timeframe = context_from(record, parent)
        return Candle(
            source_record=record.key or record.source,
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
            open_time=parse_timestamp(item[0]) if len(item) > 0 else None,
            close_time=parse_timestamp(item[6]) if len(item) > 6 else None,
            open=float_or_none(item[1]) if len(item) > 1 else None,
            high=float_or_none(item[2]) if len(item) > 2 else None,
            low=float_or_none(item[3]) if len(item) > 3 else None,
            close=float_or_none(item[4]) if len(item) > 4 else None,
            volume=float_or_none(item[5]) if len(item) > 5 else None,
            final=bool_or_none(first_value(raw, ("closed", "final", "x"))),
            raw=raw,
        )
    if not isinstance(item, dict):
        return None
    merged = {**parent, **item}
    symbol, exchange, timeframe = context_from(record, merged)
    return Candle(
        source_record=record.key or record.source,
        exchange=exchange,
        symbol=symbol,
        timeframe=timeframe,
        open_time=first_timestamp(merged, ("open_time", "candle_open_time", "time_period_start", "ts", "timestamp", "t")),
        close_time=first_timestamp(merged, ("close_time", "candle_close_time", "time_period_end", "end_time", "T")),
        open=float_or_none(first_value(merged, ("open", "o"))),
        high=float_or_none(first_value(merged, ("high", "h"))),
        low=float_or_none(first_value(merged, ("low", "l"))),
        close=float_or_none(first_value(merged, ("close", "c"))),
        volume=float_or_none(first_value(merged, ("volume", "v", "base_volume"))),
        final=bool_or_none(first_value(merged, ("is_closed", "closed", "closed_candle", "candle_closed_confirmed", "final", "x"))),
        raw=compact_record(merged),
    )


def context_from(record: SourceRecord, payload: dict[str, Any]) -> tuple[str, str, str]:
    symbol = normalize_symbol(first_value(payload, ("symbol", "asset", "market")))
    exchange = normalize_exchange(first_value(payload, ("exchange", "source_exchange", "source")))
    timeframe = normalize_timeframe(first_value(payload, ("timeframe", "interval", "tf", "period_id")))
    text = f"{record.key or ''}:{record.source}"
    if symbol == "unknown":
        match = re.search(r"(?:^|:)([A-Z0-9]{3,20}USDT|[A-Z0-9]{3,20}-PERP)(?:$|:|/|_)", text.upper())
        if match:
            symbol = normalize_symbol(match.group(1))
    if exchange == "unknown":
        for candidate in ("binance", "kucoin", "coinapi", "coinank"):
            if candidate in text.lower():
                exchange = candidate
                break
    if timeframe == "unknown":
        match = re.search(r"(?:^|:|/|_)(1m|3m|5m|15m|30m|1h|2h|4h|1d)(?:$|:|/|_)", text.lower())
        if match:
            timeframe = match.group(1)
    return symbol, exchange, timeframe


def infer_key(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("key", "redis_key", "stream", "topic", "id", "prediction_id", "sample_id"):
            if key in value:
                return str(value[key])
    return None


def with_source(item: dict[str, Any], record: SourceRecord) -> dict[str, Any]:
    merged = dict(item)
    merged.setdefault("_source", record.source)
    if record.key is not None:
        merged.setdefault("_key", record.key)
    return merged


def first_value(payload: Any, keys: Iterable[str]) -> Any:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def first_timestamp(payload: Any, keys: Iterable[str]) -> int | None:
    value = first_value(payload, keys)
    return parse_timestamp(value)


def parse_timestamp(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if re.fullmatch(r"-?\d+(\.\d+)?", text):
            return int(float(text))
        try:
            normalized = text.replace("Z", "+00:00")
            return int(datetime.fromisoformat(normalized).timestamp() * 1000)
        except ValueError:
            return None
    return None


def normalize_ms(value: int | float) -> int:
    numeric = int(value)
    if abs(numeric) < 10_000_000_000:
        return numeric * 1000
    return numeric


def timeframe_to_seconds(timeframe: str) -> int | None:
    return TIMEFRAME_SECONDS.get(normalize_timeframe(timeframe))


def normalize_symbol(value: Any) -> str:
    if value is None:
        return "unknown"
    text = str(value).upper().replace("/", "").replace("-", "")
    aliases = {"XBTUSDT": "BTCUSDT"}
    return aliases.get(text, text) if text else "unknown"


def normalize_exchange(value: Any) -> str:
    if value is None:
        return "unknown"
    text = str(value).lower()
    for candidate in ("binance", "kucoin", "coinapi", "coinank"):
        if candidate in text:
            return candidate
    return text or "unknown"


def normalize_timeframe(value: Any) -> str:
    if value is None:
        return "unknown"
    text = str(value).lower().replace("period_", "")
    aliases = {"1min": "1m", "5min": "5m", "15min": "15m", "1hour": "1h", "4hour": "4h"}
    return aliases.get(text, text)


def float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def numeric_value(value: Any) -> float | None:
    return float_or_none(value)


def bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def truthy(value: Any) -> bool:
    return bool_or_none(value) is True


def has_pending_items(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    if isinstance(value, str):
        text = value.strip().lower()
        return text not in {"", "0", "false", "none", "null", "[]", "{}"}
    if isinstance(value, (int, float)):
        return value != 0
    return bool(value)


def candle_has_valid_close(candle: Candle, interval: int | None) -> bool:
    if candle.open_time is None:
        return False
    if candle.close_time is None:
        return False
    open_ms = normalize_ms(candle.open_time)
    close_ms = normalize_ms(candle.close_time)
    if close_ms <= open_ms:
        return False
    if interval and close_ms < open_ms + interval * 1000 - 1000:
        return False
    return True


def is_closed_candle_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in ("ohlcv", "kline", "candle")) and "current" not in lowered and "open" not in lowered


def has_abnormal_ohlc(candle: Candle) -> bool:
    values = [candle.open, candle.high, candle.low, candle.close]
    if any(value is None for value in values):
        return False
    open_, high, low, close = values
    assert open_ is not None and high is not None and low is not None and close is not None
    if min(open_, high, low, close) <= 0:
        return True
    if high < low:
        return True
    if not (low <= open_ <= high):
        return True
    return not (low <= close <= high)


def latest_candle_at_or_before(rows: list[Candle], decision_time: int) -> Candle | None:
    decision_ms = normalize_ms(decision_time)
    latest: Candle | None = None
    for candle in rows:
        close_or_expected = candle_close_or_expected(candle)
        if close_or_expected is None:
            continue
        if normalize_ms(close_or_expected) <= decision_ms:
            latest = candle
        else:
            break
    return latest


def candle_close_or_expected(candle: Candle) -> int | None:
    if candle.close_time is not None:
        return candle.close_time
    interval = timeframe_to_seconds(candle.timeframe)
    if interval and candle.open_time is not None:
        return normalize_ms(candle.open_time) + interval * 1000
    return candle.open_time


def candle_summary(candle: Candle | None) -> dict[str, Any] | None:
    if candle is None:
        return None
    return {
        "exchange": candle.exchange,
        "symbol": candle.symbol,
        "timeframe": candle.timeframe,
        "open_time": candle.open_time,
        "close_time": candle.close_time,
        "final": candle.final,
    }


def extract_feature_vector(feature: dict[str, Any]) -> dict[str, Any]:
    vector = feature.get("features")
    if isinstance(vector, dict):
        return vector
    excluded = {
        "symbol",
        "exchange",
        "timeframe",
        "interval",
        "generated_at",
        "generated_utc",
        "timestamp",
        "feature_timestamp",
        "feature_version",
        "feature_hash",
        "feature_snapshot_id",
        "source_candle_timestamps",
        "stale_feature_flags",
        "_source",
        "_key",
    }
    return {key: value for key, value in feature.items() if key not in excluded}


def count_invalid_values(value: Any) -> int:
    if value is None:
        return 1
    if isinstance(value, float):
        return 0 if math.isfinite(value) else 1
    if isinstance(value, int) and not isinstance(value, bool):
        return 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        return 1 if lowered in {"nan", "inf", "+inf", "-inf", "infinity", "null", "none"} else 0
    if isinstance(value, dict):
        return sum(count_invalid_values(child) for child in value.values())
    if isinstance(value, list):
        return sum(count_invalid_values(child) for child in value)
    return 0


def stale_feature_count(feature: dict[str, Any]) -> int:
    flags = feature.get("stale_feature_flags")
    if isinstance(flags, list):
        return len(flags)
    if isinstance(flags, dict):
        return sum(1 for value in flags.values() if truthy(value))
    count = numeric_value(feature.get("stale_feature_count"))
    if count is not None:
        return int(count)
    state = str(feature.get("feature_freshness_state") or "").upper()
    return 1 if state == "STALE" else 0


def source_candle_timestamps(feature: dict[str, Any]) -> list[int]:
    values: list[int] = []
    explicit = feature.get("source_candle_timestamps")
    if isinstance(explicit, list):
        values.extend(timestamp for timestamp in (parse_timestamp(item) for item in explicit) if timestamp is not None)
    for key in (
        "source_candle_timestamp",
        "source_candle_time",
        "source_event_time",
        "source_available_time",
        "available_at",
        "candle_open_time",
        "candle_close_time",
        "feature_cutoff",
    ):
        timestamp = parse_timestamp(feature.get(key))
        if timestamp is not None:
            values.append(timestamp)
    source_inputs = feature.get("source_inputs")
    if isinstance(source_inputs, dict):
        for child in source_inputs.values():
            if isinstance(child, dict):
                timestamp = first_timestamp(child, ("timestamp", "ts", "generated_at", "event_time", "candle_close_time"))
                if timestamp is not None:
                    values.append(timestamp)
    return values


def explicit_forward_fill_flag(feature: dict[str, Any]) -> bool:
    return any(
        truthy(feature.get(key))
        for key in ("forward_filled", "forward_fill", "interpolated", "silent_forward_fill", "ffill")
    )


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def directional_opinion(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        lowered = value.lower()
        if "long" in lowered or lowered in {"buy", "bullish"}:
            return "long"
        if "short" in lowered or lowered in {"sell", "bearish"}:
            return "short"
        if "hold" in lowered or "flat" in lowered:
            return "hold"
    numeric = float_or_none(value)
    if numeric is None:
        return None
    if numeric > 0.55:
        return "long"
    if numeric < 0.45:
        return "short"
    return "hold"


def ppo_directional_opinion(decision: dict[str, Any]) -> str | None:
    explicit = directional_opinion(first_value(decision, ("ppo_direction", "selected_action", "action")))
    if explicit:
        return explicit
    probabilities = decision.get("action_probabilities") or decision.get("ppo_action_probabilities")
    if isinstance(probabilities, dict):
        if not probabilities:
            return None
        action = max(probabilities.items(), key=lambda item: float_or_none(item[1]) or float("-inf"))[0]
        return directional_opinion(action)
    return None


def collect_dirty_training_flags(sample: dict[str, Any], classification: str) -> list[str]:
    flags: list[str] = []
    if classification and classification not in {"TRAINABLE", "CLEAN", "VALID"}:
        flags.append(f"classification:{classification}")
    if stale_feature_count(sample):
        flags.append("stale_features")
    if count_invalid_values(extract_feature_vector(sample)):
        flags.append("invalid_feature_values")
    if truthy(first_value(sample, ("future_leakage", "lookahead", "uses_future_data"))):
        flags.append("future_leakage")
    if truthy(first_value(sample, ("missing_candles", "incomplete_candles", "source_stale"))):
        flags.append("source_incomplete_or_stale")
    if sample.get("trust_schema_version"):
        accepted_for_training = sample.get("accepted_for_training")
        if accepted_for_training is False:
            flags.append("accepted_for_training_false")
        replay_id = sample.get("replay_snapshot_id")
        if replay_id is None or replay_id == "" or replay_id is False:
            flags.append("replay_snapshot_missing")
        if truthy(first_value(sample, ("quarantined", "is_quarantined"))):
            flags.append("quarantined")
    return flags


def transition_is_invalid(position_before: Any, requested_action: str, position_after: Any) -> bool:
    if not requested_action:
        return False
    before_side = position_side(position_before)
    after_side = position_side(position_after)
    if requested_action in {"hold", "abstain", "none", "no_trade"} and positions_differ(position_before, position_after):
        return True
    if requested_action in {"open_long", "long", "buy"} and before_side == "short" and after_side == "long":
        return True
    if requested_action in {"open_short", "short", "sell"} and before_side == "long" and after_side == "short":
        return True
    return False


def position_side(position: Any) -> str:
    if position is None:
        return "flat"
    if isinstance(position, str):
        lowered = position.lower()
        if "long" in lowered:
            return "long"
        if "short" in lowered:
            return "short"
        if "flat" in lowered or "none" in lowered:
            return "flat"
    if isinstance(position, dict):
        side = first_value(position, ("side", "position_side", "direction"))
        if side is not None:
            return position_side(side)
        qty = numeric_value(first_value(position, ("qty", "quantity", "positionAmt", "size")))
        if qty is not None:
            if qty > 0:
                return "long"
            if qty < 0:
                return "short"
            return "flat"
    numeric = numeric_value(position)
    if numeric is not None:
        if numeric > 0:
            return "long"
        if numeric < 0:
            return "short"
    return "unknown"


def positions_differ(left: Any, right: Any) -> bool:
    if left == right:
        return False
    left_num = numeric_value(left)
    right_num = numeric_value(right)
    if left_num is not None and right_num is not None:
        return abs(left_num - right_num) > 1e-12
    return position_side(left) != position_side(right)


def compact_record(value: Any, limit: int = 30) -> dict[str, Any]:
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for index, (key, child) in enumerate(value.items()):
            if index >= limit:
                compact["..."] = f"{len(value) - limit} more fields"
                break
            if isinstance(child, dict):
                compact[key] = compact_record(child, max(5, limit // 3))
            elif isinstance(child, list):
                compact[key] = child[:5]
                if len(child) > 5:
                    compact[f"{key}_truncated"] = len(child) - 5
            else:
                compact[key] = child
        return compact
    return {"value": value}


def escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


if __name__ == "__main__":
    raise SystemExit(main())
