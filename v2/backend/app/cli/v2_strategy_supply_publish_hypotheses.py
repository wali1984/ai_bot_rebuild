"""Publish current strategy-supply hypotheses into Redis.

This CLI keeps the positive-USD strategy supply available to the A+ inventory
loop. It only reads existing runtime telemetry and writes ``v2:strategy_supply``
keys; it never places, cancels, tests, or modifies exchange orders.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from v2.backend.app.services.paper_trade_management.entry_gate import (
    expected_move_after_cost_favorable_for_side,
)
from v2.backend.app.services.strategy_supply.edge_hypothesis_generator import (
    GATE_CLEAN_POSITIVE_HYPOTHESIS_KEY,
    HYPOTHESIS_KEY,
    HYPOTHESIS_TTL_SECONDS,
    LATEST_ERROR_SUMMARY_KEY,
    LATEST_POSITIVE_SUMMARY_KEY,
    POSITIVE_HYPOTHESIS_KEY,
    STATUS_KEY,
    STRATEGY_FAMILIES,
    generate_hypotheses,
)
from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _redis_client() -> Any:
    try:
        import redis  # type: ignore
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("redis package is required for strategy supply publishing") from exc
    url = os.environ.get("V2_REDIS_URL") or os.environ.get("REDIS_URL") or "redis://127.0.0.1:6379/0"
    # Binary responses are required so strategy supply can validate and hash
    # the exact canonical closed-OHLCV bytes.  All JSON readers in the called
    # services decode bytes explicitly; a decode_responses=True client would
    # force the causal TA boundary to mask the source.
    client = redis.Redis.from_url(
        url,
        decode_responses=False,
        socket_connect_timeout=1.0,
        socket_timeout=5.0,
    )
    client.ping()
    return client


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, default=str, separators=(",", ":")) + "\n")


def _float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _selected_side_economics_consistent(row: Mapping[str, Any]) -> bool:
    side = str(row.get("side") or "").strip().lower()
    if side not in {"long", "short"}:
        return False
    expected_move_after_cost_bps = _float_or_none(row.get("expected_move_after_cost_bps"))
    if (
        expected_move_after_cost_bps is not None
        and not expected_move_after_cost_favorable_for_side(
            side=side,
            expected_move_after_cost_bps=expected_move_after_cost_bps,
        )
    ):
        return False
    selected_edge = _float_or_none(
        row.get(f"expected_{side}_net_edge_bps")
        if row.get(f"expected_{side}_net_edge_bps") is not None
        else row.get(f"{side}_expected_net_edge_bps")
    )
    selected_net = _float_or_none(
        row.get(f"{side}_expected_net_pnl_usd")
        if row.get(f"{side}_expected_net_pnl_usd") is not None
        else row.get(f"expected_{side}_net_pnl_usd")
    )
    if selected_edge is not None and selected_net is not None and selected_edge <= 0.0 < selected_net:
        return False
    return True


def _positive_net_usd(row: dict[str, Any]) -> bool:
    if not row.get("side"):
        return False
    try:
        net = float(row.get("expected_net_pnl_usd"))
    except (TypeError, ValueError):
        return False
    return net > 0.0 and _selected_side_economics_consistent(row)


def _row_rejection_reason(row: Mapping[str, Any]) -> str | None:
    reason = row.get("reason_if_rejected")
    if reason in (None, ""):
        reason = row.get("why_rejected")
    return str(reason) if reason not in (None, "") else None


def _reason_category(reason: str | None) -> str:
    upper = str(reason or "").upper()
    if not upper:
        return "accepted"
    if "STRATEGY_GENERATOR_FAILURE" in upper:
        return "strategy_generator_failure"
    if "PRICE" in upper:
        return "price_missing"
    if any(token in upper for token in ("MICROSTRUCTURE", "ORDERBOOK", "TAPE")):
        return "microstructure_missing_or_weak"
    if any(token in upper for token in ("COINANK", "COINGLASS", "MORALIS", "PROVIDER")):
        return "provider_missing"
    if any(token in upper for token in ("ATR", "FEATURE", "INPUT")):
        return "input_missing"
    if any(token in upper for token in ("EXPECTED_NET", "REWARD_TO_RISK", "NO_STRUCTURE_SIGNAL")):
        return "true_no_edge"
    return "other_rejection"


def _status_from_rows(
    *,
    all_rows: list[dict[str, Any]],
    positive_rows: list[dict[str, Any]],
    gate_clean_positive_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    rejection_reasons = [_row_rejection_reason(row) for row in all_rows]
    rejection_counts = Counter(reason for reason in rejection_reasons if reason)
    rejection_category_counts = Counter(_reason_category(reason) for reason in rejection_reasons if reason)
    positive_rejection_counts = Counter(
        _row_rejection_reason(row)
        for row in positive_rows
        if _row_rejection_reason(row)
    )
    if not all_rows:
        status = "RED_ZERO_HYPOTHESES"
        reason = "strategy_generator_failure:no_rows_returned"
    elif not positive_rows:
        dominant_category = (
            rejection_category_counts.most_common(1)[0][0]
            if rejection_category_counts
            else "true_no_edge"
        )
        if dominant_category == "strategy_generator_failure":
            status = "RED_STRATEGY_GENERATOR_FAILURE"
        elif dominant_category in {"input_missing", "provider_missing", "price_missing", "microstructure_missing_or_weak"}:
            status = f"GRAY_{dominant_category.upper()}"
        else:
            status = "YELLOW_TRUE_NO_POSITIVE_EDGE"
        reason = dominant_category
    elif not gate_clean_positive_rows:
        status = "YELLOW_POSITIVE_HYPOTHESES_STAGE_REJECTED"
        reason = (
            positive_rejection_counts.most_common(1)[0][0]
            if positive_rejection_counts
            else "positive_rows_rejected_by_stage_gate"
        )
    else:
        status = "GREEN_PUBLISHING_GATE_CLEAN_POSITIVES"
        reason = "gate_clean_positive_hypotheses_available"
    return {
        "status": status,
        "status_reason": reason,
        "rejection_reason_counts": dict(sorted(rejection_counts.items())),
        "rejection_category_counts": dict(sorted(rejection_category_counts.items())),
        "positive_rejection_reason_counts": dict(sorted(positive_rejection_counts.items())),
    }


def _generator_failure_row(symbol: str, timeframe: str, generated_utc: str, exc: Exception) -> dict[str, Any]:
    reason = f"STRATEGY_GENERATOR_FAILURE:{type(exc).__name__}"
    digest = hashlib.sha256(f"{symbol}|{timeframe}|{generated_utc}|{reason}".encode("utf-8")).hexdigest()
    return {
        "schema_version": "edge_hypothesis_v1",
        "hypothesis_id": f"hyp_{digest[:16]}",
        "strategy_id": f"hyp_{digest[:16]}",
        "symbol": symbol,
        "timeframe": timeframe,
        "side": None,
        "strategy_family": None,
        "strategy_subtype": "degraded_strategy_generator_failure",
        "generated_utc": generated_utc,
        "generated_at": generated_utc,
        "failure_observed_at": generated_utc,
        # A caught exception does not create market evidence, a feature
        # cutoff, or a strategy decision.  The row is not available as a
        # retained output until a post-commit readback receipt exists.
        "feature_cutoff": None,
        "decision_time": None,
        "available_at": None,
        "input_available_at": None,
        "output_postcommit_readback_receipt_emitted": False,
        "output_available_at_unavailable_until_postcommit_receipt": True,
        "expected_gross_pnl_usd": None,
        "expected_cost_usd": None,
        "expected_net_pnl_usd": None,
        "expected_max_loss_usd": None,
        "reward_to_risk": None,
        "loss_probability": None,
        "current_price": None,
        "price_source": None,
        "feature_vector_hash": f"strategy_supply_{digest[:32]}",
        "provider_features_used": [],
        "provider_feature_hashes": {},
        "microstructure_trust": None,
        "squeeze_risk": None,
        "liquidation_cluster_distance_usd": None,
        "hedge_required": False,
        "exit_plan": {"status": "NO_EXIT_PLAN", "reason": reason},
        "reason_if_rejected": reason,
        "why_rejected": reason,
        "places_real_order": False,
        "routes_to_live": False,
        "counts_as_a_plus": False,
        "counts_as_live_ready": False,
        "counts_as_final_a_plus": False,
        "consumer_eligible": False,
        "trainer_consumable": False,
        "trainer_admission_granted": False,
        "paper_only": True,
        "live_execution_authorized": False,
    }


def publish_strategy_supply(
    *,
    client: Any,
    symbols: list[str],
    timeframes: list[str],
    ttl_seconds: int = HYPOTHESIS_TTL_SECONDS,
    cadence_seconds: float | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    generated_utc = _utc_now()
    all_rows: list[dict[str, Any]] = []
    positive_rows: list[dict[str, Any]] = []
    gate_clean_positive_rows: list[dict[str, Any]] = []
    no_data = 0
    redis_keys_written: list[str] = []
    generator_failure_count = 0
    effective_ttl_seconds = int(ttl_seconds)
    if cadence_seconds is not None and cadence_seconds > 0:
        effective_ttl_seconds = max(effective_ttl_seconds, int(cadence_seconds * 4))

    for symbol in symbols:
        normalized_symbol = str(symbol or "").upper()
        if not normalized_symbol:
            continue
        for timeframe in timeframes:
            normalized_timeframe = str(timeframe or "").strip()
            if not normalized_timeframe:
                continue
            try:
                rows = generate_hypotheses(client, normalized_symbol, normalized_timeframe)
            except Exception as exc:  # noqa: BLE001 - status must carry exact runtime failure.
                rows = [_generator_failure_row(normalized_symbol, normalized_timeframe, generated_utc, exc)]
                generator_failure_count += 1
            positive_for_key = [row for row in rows if _positive_net_usd(row)]
            gate_clean_for_key = [
                row for row in positive_for_key if _row_rejection_reason(row) is None
            ]
            all_rows.extend(rows)
            positive_rows.extend(positive_for_key)
            gate_clean_positive_rows.extend(gate_clean_for_key)
            no_data += sum(1 for row in rows if row.get("strategy_family") is None)
            key = HYPOTHESIS_KEY.format(symbol=normalized_symbol, timeframe=normalized_timeframe)
            client.set(
                key,
                json.dumps({"rows": rows, "generated_utc": generated_utc}, sort_keys=True, default=str),
                ex=effective_ttl_seconds,
            )
            redis_keys_written.append(key)
            positive_key = POSITIVE_HYPOTHESIS_KEY.format(
                symbol=normalized_symbol,
                timeframe=normalized_timeframe,
            )
            client.set(
                positive_key,
                json.dumps({"rows": positive_for_key, "generated_utc": generated_utc}, sort_keys=True, default=str),
                ex=effective_ttl_seconds,
            )
            redis_keys_written.append(positive_key)
            gate_clean_key = GATE_CLEAN_POSITIVE_HYPOTHESIS_KEY.format(
                symbol=normalized_symbol,
                timeframe=normalized_timeframe,
            )
            client.set(
                gate_clean_key,
                json.dumps({"rows": gate_clean_for_key, "generated_utc": generated_utc}, sort_keys=True, default=str),
                ex=effective_ttl_seconds,
            )
            redis_keys_written.append(gate_clean_key)

    status_details = _status_from_rows(
        all_rows=all_rows,
        positive_rows=positive_rows,
        gate_clean_positive_rows=gate_clean_positive_rows,
    )
    latest_positive_summary = {
        "schema_version": "strategy_supply_latest_positive_summary_v1",
        "generated_utc": generated_utc,
        "positive_hypothesis_count": len(positive_rows),
        "gate_clean_positive_hypothesis_count": len(gate_clean_positive_rows),
        "positive_symbols": sorted({str(row.get("symbol")) for row in positive_rows if row.get("symbol")}),
        "positive_timeframes": sorted({str(row.get("timeframe")) for row in positive_rows if row.get("timeframe")}),
        "sample_hypothesis_ids": [
            str(row.get("hypothesis_id") or row.get("strategy_id"))
            for row in positive_rows[:25]
        ],
        "places_real_order": False,
        "routes_to_live": False,
    }
    latest_error_summary = {
        "schema_version": "strategy_supply_latest_error_summary_v1",
        "generated_utc": generated_utc,
        "status": status_details["status"],
        "status_reason": status_details["status_reason"],
        "rejection_reason_counts": status_details["rejection_reason_counts"],
        "rejection_category_counts": status_details["rejection_category_counts"],
        "positive_rejection_reason_counts": status_details["positive_rejection_reason_counts"],
        "generator_failure_count": generator_failure_count,
    }
    client.set(
        LATEST_POSITIVE_SUMMARY_KEY,
        json.dumps(latest_positive_summary, sort_keys=True, default=str),
        ex=effective_ttl_seconds,
    )
    redis_keys_written.append(LATEST_POSITIVE_SUMMARY_KEY)
    client.set(
        LATEST_ERROR_SUMMARY_KEY,
        json.dumps(latest_error_summary, sort_keys=True, default=str),
        ex=effective_ttl_seconds,
    )
    redis_keys_written.append(LATEST_ERROR_SUMMARY_KEY)
    status = {
        "schema_version": "strategy_supply_publish_status_v1",
        "generated_utc": generated_utc,
        "status": status_details["status"],
        "status_reason": status_details["status_reason"],
        "symbol_count": len(symbols),
        "timeframe_count": len(timeframes),
        "hypothesis_count": len(all_rows),
        "positive_hypothesis_count": len(positive_rows),
        "gate_clean_positive_hypothesis_count": len(gate_clean_positive_rows),
        "stage_rejected_positive_hypothesis_count": len(positive_rows) - len(gate_clean_positive_rows),
        "no_data_rows": no_data,
        "generator_failure_count": generator_failure_count,
        "rejection_reason_counts": status_details["rejection_reason_counts"],
        "rejection_category_counts": status_details["rejection_category_counts"],
        "positive_rejection_reason_counts": status_details["positive_rejection_reason_counts"],
        "strategy_families": list(STRATEGY_FAMILIES),
        "redis_keys_written": redis_keys_written,
        "ttl_seconds": effective_ttl_seconds,
        "requested_ttl_seconds": int(ttl_seconds),
        "publish_cadence_seconds": cadence_seconds,
        "ttl_longer_than_three_publish_cadences": (
            None if cadence_seconds is None or cadence_seconds <= 0 else effective_ttl_seconds > cadence_seconds * 3
        ),
        "approves_trade_alone": False,
        "routes_to_live": False,
        "places_real_order": False,
        "test_order_submitted": False,
        "cancel_or_modify_order": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "transfer_or_withdrawal": False,
        "live_gate_required": "blocked_human_only",
    }
    client.set(STATUS_KEY, json.dumps(status, sort_keys=True, default=str), ex=effective_ttl_seconds)
    redis_keys_written.append(STATUS_KEY)

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "strategy_supply_publish_status.json").write_text(
            json.dumps(status, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        _write_jsonl(output_dir / "strategy_supply_hypothesis_inventory.jsonl", all_rows)
        _write_jsonl(output_dir / "strategy_supply_positive_hypotheses.jsonl", positive_rows)
        _write_jsonl(output_dir / "strategy_supply_gate_clean_positive_hypotheses.jsonl", gate_clean_positive_rows)

    return status


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="v2_strategy_supply_publish_hypotheses")
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--timeframes", default="1m,5m,15m,1h,4h")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--ttl-seconds", type=int, default=HYPOTHESIS_TTL_SECONDS)
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    symbols = resolve_symbols(
        explicit=_parse_csv(args.symbols),
        smoke_test=bool(args.smoke_test),
        include_baseline=True,
    )
    timeframes = _parse_csv(args.timeframes) or ["1m", "5m", "15m", "1h", "4h"]
    client = _redis_client()
    cycle = 0
    last_status: dict[str, Any] | None = None
    while True:
        cycle += 1
        last_status = publish_strategy_supply(
            client=client,
            symbols=symbols,
            timeframes=timeframes,
            ttl_seconds=int(args.ttl_seconds),
            cadence_seconds=float(args.interval_seconds) if args.loop else None,
            output_dir=Path(args.output_dir) if args.output_dir else None,
        )
        if args.json:
            print(json.dumps(last_status, indent=2, sort_keys=True, default=str), flush=True)
        else:
            print(
                f"published {last_status['hypothesis_count']} strategy hypotheses "
                f"({last_status['positive_hypothesis_count']} positive, "
                f"{last_status['gate_clean_positive_hypothesis_count']} gate-clean) "
                f"for {last_status['symbol_count']} symbols "
                f"status={last_status['status']}",
                flush=True,
            )
        if not args.loop:
            break
        if args.max_cycles is not None and cycle >= int(args.max_cycles):
            break
        time.sleep(max(1.0, float(args.interval_seconds)))
    return 0 if last_status is not None else 1


if __name__ == "__main__":
    sys.exit(main())
