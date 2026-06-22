"""Publish professional market chart payloads from existing V2 runtime data.

This publisher is read-only. It builds chart JSON from V2-owned Redis keys:

* ``v2:market:ohlcv:binance:{symbol}:{timeframe}`` for OHLCV candles
* ``v2:features:ta:{symbol}:{timeframe}`` for TA evidence/latest values
* ``v2:prediction:{symbol}:{timeframe}`` and ``v2:signals:paper:*`` for RL
  signal and target overlays

It does not call Binance, KuCoin, CoinAPI, TradingView, or any exchange API.
It does not write Redis and cannot enable live/canary trading.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


WORKER_ID = "v2_professional_market_chart_payload_publisher"
DEFAULT_OUTPUT_DIR = Path("v2/frontend/public/operator_runtime/v2_professional_market_chart/latest")
DEFAULT_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
SMOKE_FALLBACK_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
REPO_ROOT = Path(__file__).resolve().parents[4]
V2_ROOT = REPO_ROOT / "v2"
DEFAULT_SYMBOL_UNIVERSE_PATHS = (
    Path("v2/frontend/public/operator_runtime/symbol_universe/latest/symbol_universe_status.json"),
    V2_ROOT / "frontend" / "public" / "operator_runtime" / "symbol_universe" / "latest" / "symbol_universe_status.json",
    Path("v2/frontend/public/operator_runtime/v2_kucoin_ingestor/latest/v2_kucoin_ingestor_status.json"),
    V2_ROOT / "frontend" / "public" / "operator_runtime" / "v2_kucoin_ingestor" / "latest" / "v2_kucoin_ingestor_status.json",
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _est_iso() -> str:
    return datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


def _connect_redis() -> Any | None:
    try:
        import redis  # type: ignore

        url = os.getenv("V2_REDIS_URL") or os.getenv("REDIS_URL") or "redis://127.0.0.1:6379/0"
        client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=1.0)
        client.ping()
        return client
    except Exception:
        return None


def _json_loads(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return None
    return raw


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _as_symbol_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        symbol = item.strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return tuple(out)


def _resolve_universe_symbols() -> tuple[str, ...]:
    for path in DEFAULT_SYMBOL_UNIVERSE_PATHS:
        payload = _read_json_file(path)
        if not payload:
            continue
        for field in (
            "live_data_symbols",
            "paper_symbols",
            "discovered_symbols",
            "dynamic_discovered_symbols",
            "training_symbols",
            "binance_usdm_confirmed_symbols",
            "symbols_v2",
        ):
            symbols = _as_symbol_list(payload.get(field))
            if len(symbols) > len(SMOKE_FALLBACK_SYMBOLS):
                return symbols
    return SMOKE_FALLBACK_SYMBOLS


def _parse_csv(raw: str | None, default: Iterable[str]) -> tuple[str, ...]:
    if raw is None or not raw.strip():
        return tuple(default)
    if raw.strip().lower() in {"auto", "all", "universe"}:
        return _resolve_universe_symbols()
    out: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        value = value.upper() if value.lower() not in DEFAULT_TIMEFRAMES else value.lower()
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return tuple(out) or tuple(default)


def _to_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _to_int(value: Any) -> int | None:
    try:
        out = int(float(value))
    except (TypeError, ValueError):
        return None
    return out


def _timestamp_ms_from_iso(value: Any) -> int | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    return int(parsed.timestamp() * 1000)


def _timeframe_seconds(timeframe: str) -> int:
    return {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "4h": 14400,
    }.get(timeframe, 60)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _get_json(redis_client: Any | None, key: str) -> Any:
    if redis_client is None:
        return None
    try:
        return _json_loads(redis_client.get(key))
    except Exception:
        return None


def _ohlcv_key(symbol: str, timeframe: str) -> str:
    return f"v2:market:ohlcv:binance:{symbol}:{timeframe}"


def _ohlcv_source_key(symbol: str, timeframe: str) -> str:
    return f"v2:market:ohlcv:binance:{symbol}:{timeframe}:source"


def _ta_key(symbol: str, timeframe: str) -> str:
    return f"v2:features:ta:{symbol}:{timeframe}"


def _prediction_key(symbol: str, timeframe: str) -> str:
    return f"v2:prediction:{symbol}:{timeframe}"


def _signal_key(symbol: str, timeframe: str) -> str:
    return f"v2:signals:paper:{symbol}:{timeframe}"


def _normalize_ohlcv(raw: Any, max_candles: int) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    candles: list[dict[str, Any]] = []
    for row in raw[-max(1, int(max_candles)) :]:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        open_time = _to_int(row[0])
        open_px = _to_float(row[1])
        high_px = _to_float(row[2])
        low_px = _to_float(row[3])
        close_px = _to_float(row[4])
        volume = _to_float(row[5])
        close_time = _to_int(row[6]) if len(row) > 6 else None
        quote_volume = _to_float(row[7]) if len(row) > 7 else None
        trade_count = _to_int(row[8]) if len(row) > 8 else None
        taker_buy_base = _to_float(row[9]) if len(row) > 9 else None
        taker_buy_quote = _to_float(row[10]) if len(row) > 10 else None
        if None in (open_time, open_px, high_px, low_px, close_px, volume):
            continue
        if min(open_px or 0.0, high_px or 0.0, low_px or 0.0, close_px or 0.0) <= 0:
            continue
        candles.append(
            {
                "time": int(open_time / 1000),
                "open_time_ms": open_time,
                "close_time_ms": close_time,
                "open": open_px,
                "high": high_px,
                "low": low_px,
                "close": close_px,
                "volume": volume,
                "quote_volume": quote_volume,
                "trade_count": trade_count,
                "taker_buy_base_volume": taker_buy_base,
                "taker_buy_quote_volume": taker_buy_quote,
            }
        )
    return candles


def _sma(candles: list[dict[str, Any]], period: int) -> list[dict[str, float | int]]:
    rows: list[dict[str, float | int]] = []
    closes = [float(c["close"]) for c in candles]
    for index in range(period - 1, len(candles)):
        window = closes[index - period + 1 : index + 1]
        rows.append({"time": candles[index]["time"], "value": sum(window) / period})
    return rows


def _ema(candles: list[dict[str, Any]], period: int) -> list[dict[str, float | int]]:
    rows: list[dict[str, float | int]] = []
    closes = [float(c["close"]) for c in candles]
    if len(closes) < period:
        return rows
    alpha = 2.0 / (period + 1.0)
    ema = sum(closes[:period]) / period
    rows.append({"time": candles[period - 1]["time"], "value": ema})
    for index in range(period, len(candles)):
        ema = closes[index] * alpha + ema * (1 - alpha)
        rows.append({"time": candles[index]["time"], "value": ema})
    return rows


def _bbands(candles: list[dict[str, Any]], period: int = 20, mult: float = 2.0) -> dict[str, list[dict[str, float | int]]]:
    upper: list[dict[str, float | int]] = []
    middle: list[dict[str, float | int]] = []
    lower: list[dict[str, float | int]] = []
    closes = [float(c["close"]) for c in candles]
    for index in range(period - 1, len(candles)):
        window = closes[index - period + 1 : index + 1]
        mean = sum(window) / period
        variance = sum((value - mean) ** 2 for value in window) / period
        std = math.sqrt(variance)
        time_value = candles[index]["time"]
        upper.append({"time": time_value, "value": mean + mult * std})
        middle.append({"time": time_value, "value": mean})
        lower.append({"time": time_value, "value": mean - mult * std})
    return {"bb_upper": upper, "bb_middle": middle, "bb_lower": lower}


def _volume_series(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for candle in candles:
        up = float(candle["close"]) >= float(candle["open"])
        out.append(
            {
                "time": candle["time"],
                "value": candle.get("volume") or 0.0,
                "color": "rgba(45, 223, 123, 0.36)" if up else "rgba(242, 85, 90, 0.36)",
            }
        )
    return out


def _target_line(candles: list[dict[str, Any]], target: float | None) -> list[dict[str, float | int]]:
    if target is None or not candles:
        return []
    return [
        {"time": candles[0]["time"], "value": target},
        {"time": candles[-1]["time"], "value": target},
    ]


def _selected_action(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    value = payload.get("selected_action") or payload.get("action")
    return str(value) if value is not None else None


def _prediction_overlay(prediction: Any, signal: Any) -> dict[str, Any]:
    pred = prediction if isinstance(prediction, dict) else {}
    sig = signal if isinstance(signal, dict) else {}
    generated = pred.get("generated_est") or sig.get("generated_est")
    age_seconds = None
    generated_ms = _timestamp_ms_from_iso(generated)
    if generated_ms is not None:
        age_seconds = max(0, int((time.time() * 1000 - generated_ms) / 1000))
    price_target = _to_float(sig.get("price_target_after_cost")) or _to_float(sig.get("price_target"))
    return {
        "status": "PRESENT" if pred or sig else "MISSING_SIGNAL_AND_PREDICTION",
        "prediction_id": pred.get("prediction_id") or sig.get("prediction_id"),
        "signal_id": sig.get("signal_id"),
        "selected_action": _selected_action(pred) or _selected_action(sig),
        "confidence_calibrated": _to_float(pred.get("confidence_calibrated") or sig.get("confidence")),
        "expected_move_bps": _to_float(pred.get("expected_move_bps")),
        "expected_move_after_cost_bps": _to_float(
            pred.get("expected_move_after_cost_bps") or sig.get("expected_move_after_cost_bps")
        ),
        "price_target": _to_float(sig.get("price_target")),
        "price_target_after_cost": _to_float(sig.get("price_target_after_cost")),
        "target_line_value": price_target,
        "generated_est": generated,
        "age_seconds": age_seconds,
        "source_prediction_key": pred.get("prediction_redis_key"),
        "source_signal_key": _signal_key(str(sig.get("symbol") or pred.get("symbol") or ""), str(sig.get("timeframe") or pred.get("timeframe") or "")),
        "live_gate": pred.get("live_gate") or sig.get("live_gate") or "blocked_human_only",
        "live_symbols": [],
        "execution_live_symbols": [],
    }


def _latest_ta(ta_payload: Any) -> dict[str, Any]:
    if not isinstance(ta_payload, dict):
        return {"status": "TA_PAYLOAD_MISSING", "indicators": {}}
    indicators = ta_payload.get("indicators")
    if not isinstance(indicators, dict):
        indicators = {}
    selected_keys = (
        "rsi_14",
        "macd",
        "macd_signal",
        "macd_hist",
        "ema_20",
        "ema_50",
        "sma_20",
        "sma_50",
        "atr_14",
        "bb_width_pct",
        "ta_BBANDS_20_upper",
        "ta_BBANDS_20_middle",
        "ta_BBANDS_20_lower",
    )
    latest = {key: _to_float(indicators.get(key)) for key in selected_keys if _to_float(indicators.get(key)) is not None}
    return {
        "status": str(ta_payload.get("classification") or "TA_PAYLOAD_PRESENT"),
        "generated_utc": ta_payload.get("generated_utc"),
        "source_redis_key": ta_payload.get("source_ohlcv_key") or ta_payload.get("legacy_redis_key_equivalent"),
        "indicator_count": ta_payload.get("indicator_count"),
        "field_count": ta_payload.get("field_count"),
        "library_used": ta_payload.get("library_used"),
        "no_zero_fill": ta_payload.get("no_zero_fill"),
        "trainer_consumable": ta_payload.get("trainer_consumable"),
        "indicators": latest,
    }


def _build_payload(
    *,
    symbol: str,
    timeframe: str,
    redis_client: Any | None,
    max_candles: int,
) -> dict[str, Any]:
    generated_utc = _utc_iso()
    generated_est = _est_iso()
    ohlcv_key = _ohlcv_key(symbol, timeframe)
    ta_key = _ta_key(symbol, timeframe)
    prediction_key = _prediction_key(symbol, timeframe)
    signal_key = _signal_key(symbol, timeframe)
    ohlcv_source_key = _ohlcv_source_key(symbol, timeframe)

    ohlcv_raw = _get_json(redis_client, ohlcv_key)
    source_meta = _get_json(redis_client, ohlcv_source_key)
    ta_payload = _get_json(redis_client, ta_key)
    prediction = _get_json(redis_client, prediction_key)
    signal = _get_json(redis_client, signal_key)

    candles = _normalize_ohlcv(ohlcv_raw, max_candles=max_candles)
    latest_candle = candles[-1] if candles else None
    source_event_age_seconds = None
    if latest_candle:
        event_ms = int(latest_candle.get("close_time_ms") or latest_candle["open_time_ms"])
        source_event_age_seconds = max(0, int((time.time() * 1000 - event_ms) / 1000))
    source_type = (
        str(source_meta.get("source_type"))
        if isinstance(source_meta, dict) and source_meta.get("source_type")
        else "EXISTING_V2_RUNTIME_OHLCV_FEED"
    )
    stale_after = max(240, _timeframe_seconds(timeframe) * 4)
    if redis_client is None:
        status = "REDIS_READ_UNAVAILABLE"
        blocker = "Redis read unavailable for professional chart payload."
    elif not candles:
        status = "OHLCV_MISSING"
        blocker = f"{ohlcv_key} missing or did not contain parseable OHLCV candles."
    elif source_event_age_seconds is not None and source_event_age_seconds > stale_after:
        status = "STALE_OHLCV"
        blocker = f"{ohlcv_key} latest candle older than {stale_after} seconds."
    else:
        status = "CURRENT"
        blocker = None

    signal_overlay = _prediction_overlay(prediction, signal)
    overlays = {
        "sma20": _sma(candles, 20),
        "ema20": _ema(candles, 20),
        "ema50": _ema(candles, 50),
        **_bbands(candles, 20, 2.0),
        "price_target": _target_line(candles, _to_float(signal_overlay.get("target_line_value"))),
    }
    return {
        "schema_version": "v2_professional_market_chart_payload_v1",
        "worker_id": WORKER_ID,
        "status": status,
        "blocker": blocker,
        "generated_utc": generated_utc,
        "generated_est": generated_est,
        "symbol": symbol,
        "timeframe": timeframe,
        "chart_source": (
            "v2_binance_kline_wss_with_v2_ta_and_signal_overlays"
            if source_type == "EXISTING_BINANCE_KLINE_WEBSOCKET_RUNTIME_FEED"
            else "v2_binance_ohlcv_with_v2_ta_and_signal_overlays"
        ),
        "source_type": source_type,
        "source_redis_key": ohlcv_key,
        "source_metadata_redis_key": ohlcv_source_key,
        "source_metadata": source_meta if isinstance(source_meta, dict) else None,
        "source_event_age_seconds": source_event_age_seconds,
        "source_stale_after_seconds": stale_after,
        "candle_count": len(candles),
        "candles": candles,
        "latest_candle": latest_candle,
        "volume": _volume_series(candles),
        "overlays": overlays,
        "ta": _latest_ta(ta_payload),
        "signal": signal_overlay,
        "lineage": {
            "ohlcv_key": ohlcv_key,
            "ohlcv_source_key": ohlcv_source_key,
            "ta_key": ta_key,
            "prediction_key": prediction_key,
            "signal_key": signal_key,
        },
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "execution_live_symbols": [],
        "safety": {
            "calls_exchange_api": False,
            "calls_binance_rest": False,
            "calls_binance_ws": False,
            "reads_binance_ws_runtime_payloads": source_type == "EXISTING_BINANCE_KLINE_WEBSOCKET_RUNTIME_FEED",
            "calls_coinapi_api": False,
            "writes_redis": False,
            "writes_old_redis": False,
            "writes_exchange_orders": False,
            "calls_test_order_endpoint": False,
            "leverage_changed": False,
            "margin_mode_changed": False,
            "approves_live": False,
            "approves_canary": False,
            "redis_trim_performed": False,
        },
    }


def publish(
    *,
    symbols: tuple[str, ...],
    timeframes: tuple[str, ...],
    output_dir: Path,
    max_candles: int,
) -> dict[str, Any]:
    redis_client = _connect_redis()
    payloads: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        for timeframe in timeframes:
            payload = _build_payload(
                symbol=symbol,
                timeframe=timeframe,
                redis_client=redis_client,
                max_candles=max_candles,
            )
            payloads[f"{symbol}:{timeframe}"] = payload
            _write_json(output_dir / f"{symbol}_{timeframe}_chart.json", payload)

    status_counts: dict[str, int] = {}
    for payload in payloads.values():
        status = str(payload.get("status") or "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1
    current_count = sum(1 for payload in payloads.values() if payload.get("status") == "CURRENT")
    non_current = [
        key for key, payload in payloads.items() if payload.get("status") != "CURRENT"
    ]
    symbols_current_all_timeframes = [
        symbol
        for symbol in symbols
        if all(payloads.get(f"{symbol}:{timeframe}", {}).get("status") == "CURRENT" for timeframe in timeframes)
    ]
    summary = {
        "schema_version": "v2_professional_market_chart_manifest_v1",
        "worker_id": WORKER_ID,
        "generated_utc": _utc_iso(),
        "generated_est": _est_iso(),
        "status": "V2_PROFESSIONAL_MARKET_CHARTS_READY"
        if current_count == len(payloads)
        else "V2_PROFESSIONAL_MARKET_CHARTS_PARTIAL",
        "symbols": list(symbols),
        "symbols_count": len(symbols),
        "timeframes": list(timeframes),
        "timeframe": timeframes[0] if timeframes else "1m",
        "total_payload_count": len(payloads),
        "current_payload_count": current_count,
        "current_symbol_all_timeframe_count": len(symbols_current_all_timeframes),
        "status_counts": status_counts,
        "non_current_payloads": non_current,
        "payloads": {
            key: {
                "path": f"/operator_runtime/v2_professional_market_chart/latest/{payload['symbol']}_{payload['timeframe']}_chart.json",
                "status": payload["status"],
                "symbol": payload["symbol"],
                "timeframe": payload["timeframe"],
                "candle_count": payload["candle_count"],
                "source_redis_key": payload["source_redis_key"],
                "source_type": payload["source_type"],
                "source_event_age_seconds": payload.get("source_event_age_seconds"),
                "latest_close": (payload.get("latest_candle") or {}).get("close"),
                "signal_action": (payload.get("signal") or {}).get("selected_action"),
                "price_target_after_cost": (payload.get("signal") or {}).get("price_target_after_cost"),
            }
            for key, payload in payloads.items()
        },
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "execution_live_symbols": [],
        "safety": {
            "calls_exchange_api": False,
            "writes_redis": False,
            "writes_old_redis": False,
            "writes_exchange_orders": False,
            "approves_live": False,
            "approves_canary": False,
            "redis_trim_performed": False,
        },
    }
    _write_json(output_dir / "operator_dashboard_payload.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="auto", help="Comma-separated symbols or auto/all/universe for the V2 symbol universe.")
    parser.add_argument("--timeframes", default=",".join(DEFAULT_TIMEFRAMES))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-candles", type=int, default=100)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=15.0)
    args = parser.parse_args(argv)
    symbols = _parse_csv(args.symbols, _resolve_universe_symbols())
    if args.symbols.strip().lower() in {"auto", "all", "universe"}:
        symbols = _resolve_universe_symbols()
    timeframes = tuple(tf for tf in _parse_csv(args.timeframes, DEFAULT_TIMEFRAMES) if tf in DEFAULT_TIMEFRAMES)
    output_dir = Path(args.output_dir)
    if args.loop:
        while True:
            summary = publish(
                symbols=symbols,
                timeframes=timeframes or DEFAULT_TIMEFRAMES,
                output_dir=output_dir,
                max_candles=int(args.max_candles),
            )
            print(
                json.dumps(
                    {
                        "status": summary["status"],
                        "generated_est": summary["generated_est"],
                        "current_payload_count": summary["current_payload_count"],
                        "total_payload_count": summary["total_payload_count"],
                        "live_gate": summary["live_gate"],
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            time.sleep(max(1.0, float(args.interval_seconds)))
    summary = publish(
        symbols=symbols,
        timeframes=timeframes or DEFAULT_TIMEFRAMES,
        output_dir=output_dir,
        max_candles=int(args.max_candles),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
