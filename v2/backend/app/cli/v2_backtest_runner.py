"""V2 Backtest Runner — standalone CLI that simulates a signal-following
strategy against historical OHLCV data stored in Redis.

SAFE INVARIANTS (never violated):
- This script never places exchange orders.
- It never mutates trading state.
- All writes go to ``v2:backtest:*`` Redis namespace only.

Usage::

    python -m v2.backend.app.cli.v2_backtest_runner \
        --symbol BTCUSDT --timeframe 1h --lookback-candles 100

Exit codes:
    0 — success
    1 — Redis/data error or no candles
    2 — validation error (bad args)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from typing import Any

GATE_STATUS = "blocked_human_only"
BACKTEST_RESULT_TTL_SECONDS = 7 * 24 * 3600  # 7 days
FEE_PER_SIDE_PCT = 0.05  # 0.05% taker fee each way -> 0.10% round-trip
VALID_TIMEFRAMES = {"1m", "3m", "5m", "15m", "1h", "4h", "1d", "1w"}

HOLD_CANDLES: dict[str, int] = {
    "1m": 5,
    "3m": 3,
    "5m": 5,
    "15m": 3,
    "1h": 1,
    "4h": 1,
    "1d": 1,
    "1w": 1,
}


def _redis_url() -> str:
    for key in ("V2_REDIS_URL", "REDIS_URL", "LEGACY_REDIS_URL"):
        v = os.environ.get(key, "").strip()
        if v:
            return v
    return "redis://localhost:6379/0"


def _get_redis_client() -> Any:
    url = _redis_url()
    try:
        import redis  # type: ignore
        client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=5.0)
        client.ping()
        return client
    except Exception as exc:
        print(f"[backtest] Redis unavailable: {exc}", file=sys.stderr)
        return None


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return None
        return result
    except (TypeError, ValueError):
        return None


def _parse_closed_candle_dict(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    open_val = _float(item.get("open"))
    close_val = _float(item.get("close"))
    if open_val is None or close_val is None:
        return None
    ts_ms = _float(item.get("open_time_ms") or item.get("time"))
    if ts_ms is not None and ts_ms < 1e10:
        ts_ms = ts_ms * 1000
    return {
        "open_time_ms": int(ts_ms or 0),
        "open": open_val,
        "high": _float(item.get("high")) or open_val,
        "low": _float(item.get("low")) or open_val,
        "close": close_val,
        "volume": _float(item.get("volume")) or 0.0,
    }


def _parse_binance_kline(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, list) or len(row) < 7:
        return None
    open_time_ms = _float(row[0])
    close_time_ms = _float(row[6])
    if open_time_ms is None or close_time_ms is None:
        return None
    now_ms = time.time() * 1000
    if close_time_ms > now_ms:
        return None
    open_val = _float(row[1])
    high_val = _float(row[2])
    low_val = _float(row[3])
    close_val = _float(row[4])
    volume_val = _float(row[5])
    if any(v is None for v in (open_val, high_val, low_val, close_val, volume_val)):
        return None
    return {
        "open_time_ms": int(open_time_ms),
        "open": open_val,
        "high": high_val,
        "low": low_val,
        "close": close_val,
        "volume": volume_val,
    }


def _load_candles(
    client: Any, symbol: str, timeframe: str, lookback: int
) -> list[dict[str, Any]]:
    closed_key = f"v2:market:ohlcv_closed:binance:{symbol}:{timeframe}"
    raw_closed = client.get(closed_key)
    if raw_closed:
        try:
            parsed = json.loads(raw_closed)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, list):
            candles = [
                c for item in parsed
                if (c := _parse_closed_candle_dict(item)) is not None
            ]
            if candles:
                candles.sort(key=lambda c: c["open_time_ms"])
                return candles[-lookback:]
        elif isinstance(parsed, dict):
            candle = _parse_closed_candle_dict(parsed)
            if candle:
                return [candle]

    raw_key = f"v2:market:ohlcv:binance:{symbol}:{timeframe}"
    raw_ohlcv = client.get(raw_key)
    if raw_ohlcv:
        try:
            parsed = json.loads(raw_ohlcv)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, list):
            candles = [
                c for row in parsed
                if (c := _parse_binance_kline(row)) is not None
            ]
            candles.sort(key=lambda c: c["open_time_ms"])
            return candles[-lookback:]

    return []


def _load_signal(client: Any, symbol: str, timeframe: str) -> dict[str, Any]:
    key = f"v2:signals:paper:{symbol}:{timeframe}"
    raw = client.get(key)
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except (ValueError, TypeError):
            pass
    pred_key = f"v2:prediction:{symbol}:{timeframe}"
    raw_pred = client.get(pred_key)
    if raw_pred:
        try:
            data = json.loads(raw_pred)
            if isinstance(data, dict):
                return data
        except (ValueError, TypeError):
            pass
    return {}


def _extract_signal_info(signal: dict[str, Any]) -> tuple[str, float, float | None]:
    raw_action = (
        signal.get("action")
        or signal.get("signal_direction")
        or signal.get("direction")
        or "long"
    )
    direction = str(raw_action).lower().strip()
    if direction not in ("long", "short", "buy", "sell"):
        direction = "long"
    if direction == "buy":
        direction = "long"
    elif direction == "sell":
        direction = "short"
    confidence = _float(signal.get("confidence")) or 0.5
    price_target = _float(
        signal.get("price_target_after_cost") or signal.get("price_target")
    )
    return direction, confidence, price_target


def _run_backtest(
    candles: list[dict[str, Any]],
    direction: str,
    confidence: float,
    price_target: float | None,
    hold_candles: int,
    symbol: str,
    timeframe: str,
) -> dict[str, Any]:
    """Core backtest engine — no exchange calls, no order placement."""
    trades: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    equity = 100.0
    peak_equity = 100.0
    max_drawdown_pct = 0.0

    min_candles_needed = hold_candles + 2
    n = len(candles)

    equity_curve.append({
        "candle_index": 0,
        "price": candles[0]["open"] if n > 0 else 0.0,
        "equity": round(equity, 6),
        "trade": None,
    })

    for i in range(n - min_candles_needed + 1):
        entry_idx = i + 1
        exit_idx = i + 1 + hold_candles

        if exit_idx >= n:
            break

        entry_price = candles[entry_idx]["open"]
        exit_price = candles[exit_idx]["open"]

        if entry_price is None or exit_price is None or entry_price <= 0:
            continue

        actual_exit_price = exit_price
        hit_tp = False
        hit_sl = False

        if price_target is not None and price_target > 0:
            tp_price = price_target
            target_dist = abs(tp_price - entry_price)
            if direction == "short":
                sl_price = entry_price + 2.0 * target_dist
            else:
                sl_price = entry_price - 2.0 * target_dist

            for hold_i in range(1, hold_candles + 1):
                check_idx = entry_idx + hold_i - 1
                if check_idx >= n:
                    break
                c = candles[check_idx]
                if direction == "short":
                    if c["low"] is not None and c["low"] <= tp_price:
                        actual_exit_price = tp_price
                        hit_tp = True
                        break
                    if c["high"] is not None and c["high"] >= sl_price:
                        actual_exit_price = sl_price
                        hit_sl = True
                        break
                else:
                    if c["high"] is not None and c["high"] >= tp_price:
                        actual_exit_price = tp_price
                        hit_tp = True
                        break
                    if c["low"] is not None and c["low"] <= sl_price:
                        actual_exit_price = sl_price
                        hit_sl = True
                        break

        if direction == "short":
            raw_pnl = (entry_price - actual_exit_price) / entry_price * 100.0
        else:
            raw_pnl = (actual_exit_price - entry_price) / entry_price * 100.0

        pnl_pct = raw_pnl - (FEE_PER_SIDE_PCT * 2)
        win = pnl_pct > 0.0
        equity *= (1 + pnl_pct / 100.0)

        if equity > peak_equity:
            peak_equity = equity
        dd = (equity - peak_equity) / peak_equity * 100.0
        if dd < max_drawdown_pct:
            max_drawdown_pct = dd

        trade = {
            "entry_candle_index": entry_idx,
            "exit_candle_index": exit_idx,
            "entry_time_ms": candles[entry_idx]["open_time_ms"],
            "exit_time_ms": candles[exit_idx]["open_time_ms"],
            "entry_price": round(entry_price, 6),
            "exit_price": round(actual_exit_price, 6),
            "pnl_pct": round(pnl_pct, 6),
            "direction": direction,
            "win": win,
            "hit_tp": hit_tp,
            "hit_sl": hit_sl,
        }
        trades.append(trade)

        equity_curve.append({
            "candle_index": exit_idx,
            "price": round(actual_exit_price, 6),
            "equity": round(equity, 6),
            "trade": {
                "direction": direction,
                "pnl_pct": round(pnl_pct, 4),
                "win": win,
            },
        })

    total_trades = len(trades)
    winning_trades = sum(1 for t in trades if t["win"])
    losing_trades = total_trades - winning_trades
    win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
    total_pnl_pct = round(equity - 100.0, 6)
    avg_pnl = total_pnl_pct / total_trades if total_trades > 0 else 0.0

    gross_profit = sum(t["pnl_pct"] for t in trades if t["pnl_pct"] > 0)
    gross_loss = abs(sum(t["pnl_pct"] for t in trades if t["pnl_pct"] < 0))
    profit_factor = (
        gross_profit / gross_loss if gross_loss > 0
        else (gross_profit if gross_profit > 0 else 0.0)
    )

    returns = [t["pnl_pct"] for t in trades]
    sharpe_estimate = 0.0
    if len(returns) > 1:
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        std_r = variance ** 0.5
        sharpe_estimate = round(mean_r / std_r, 4) if std_r > 0 else 0.0

    summary = {
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": round(win_rate, 6),
        "total_pnl_pct": round(total_pnl_pct, 6),
        "avg_pnl_per_trade_pct": round(avg_pnl, 6),
        "max_drawdown_pct": round(max_drawdown_pct, 6),
        "profit_factor": round(profit_factor, 4),
        "sharpe_estimate": sharpe_estimate,
        "signal_direction": direction,
        "signal_confidence": round(confidence, 6),
        "final_equity": round(equity, 6),
        "gross_profit_pct": round(gross_profit, 6),
        "gross_loss_pct": round(gross_loss, 6),
        "hold_candles_used": hold_candles,
        "fee_per_side_pct": FEE_PER_SIDE_PCT,
    }

    return {
        "summary": summary,
        "equity_curve": equity_curve,
        "trades": trades,
    }


def _write_results(client: Any, run_id: str, results: dict[str, Any]) -> None:
    sym = results["symbol"]
    tf = results["timeframe"]
    result_key = f"v2:backtest:results:{sym}:{tf}:{run_id}"
    index_key = "v2:backtest:index"
    score = float(results.get("started_at_ms", time.time() * 1000))
    try:
        client.set(result_key, json.dumps(results), ex=BACKTEST_RESULT_TTL_SECONDS)
        client.zadd(index_key, {result_key: score})
        client.zremrangebyrank(index_key, 0, -1001)
    except Exception as exc:
        print(f"[backtest] Warning: Redis write failed: {exc}", file=sys.stderr)


def _write_pending(client: Any, run_id: str, symbol: str, timeframe: str) -> None:
    key = f"v2:backtest:pending:{run_id}"
    try:
        client.set(
            key,
            json.dumps({"run_id": run_id, "status": "running",
                        "symbol": symbol, "timeframe": timeframe}),
            ex=3600,
        )
    except Exception:
        pass


def _clear_pending(client: Any, run_id: str) -> None:
    try:
        client.delete(f"v2:backtest:pending:{run_id}")
    except Exception:
        pass


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="V2 Backtest Runner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--lookback-candles", type=int, default=100)
    parser.add_argument("--run-id", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    symbol = "".join(ch for ch in args.symbol.upper() if ch.isalnum()) or "BTCUSDT"
    timeframe = args.timeframe if args.timeframe in VALID_TIMEFRAMES else "1h"
    lookback = max(10, min(500, args.lookback_candles))

    if args.timeframe not in VALID_TIMEFRAMES:
        print(
            f"[backtest] Invalid timeframe '{args.timeframe}'. "
            f"Valid: {sorted(VALID_TIMEFRAMES)}",
            file=sys.stderr,
        )
        return 2

    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    started_at_ms = int(time.time() * 1000)
    run_id = args.run_id or f"bt_{symbol}_{timeframe}_{started_at_ms}"

    print(
        f"[backtest] run_id={run_id} symbol={symbol} tf={timeframe} lookback={lookback}",
        file=sys.stderr,
    )

    client = _get_redis_client()
    if client is None:
        result = {
            "run_id": run_id, "symbol": symbol, "timeframe": timeframe,
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "status": "error", "error": "Redis unavailable",
            "params": {"lookback_candles": lookback},
            "summary": None, "equity_curve": [], "trades": [],
        }
        print(json.dumps(result, indent=2))
        return 1

    _write_pending(client, run_id, symbol, timeframe)

    candles = _load_candles(client, symbol, timeframe, lookback)
    if not candles:
        print(
            f"[backtest] No candle data for {symbol}:{timeframe}",
            file=sys.stderr,
        )
        result = {
            "run_id": run_id, "symbol": symbol, "timeframe": timeframe,
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "status": "error", "error": "No candle data available",
            "params": {"lookback_candles": lookback},
            "summary": None, "equity_curve": [], "trades": [],
        }
        _clear_pending(client, run_id)
        print(json.dumps(result, indent=2))
        return 1

    print(f"[backtest] Loaded {len(candles)} candles", file=sys.stderr)

    signal = _load_signal(client, symbol, timeframe)
    direction, confidence, price_target = _extract_signal_info(signal)
    hold = HOLD_CANDLES.get(timeframe, 1)

    print(
        f"[backtest] direction={direction} confidence={confidence:.4f} "
        f"price_target={price_target} hold={hold}",
        file=sys.stderr,
    )

    bt = _run_backtest(
        candles=candles,
        direction=direction,
        confidence=confidence,
        price_target=price_target,
        hold_candles=hold,
        symbol=symbol,
        timeframe=timeframe,
    )

    completed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    result: dict[str, Any] = {
        "run_id": run_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "started_at": started_at,
        "started_at_ms": started_at_ms,
        "completed_at": completed_at,
        "status": "complete",
        "gate_status": GATE_STATUS,
        "params": {
            "lookback_candles": lookback,
            "candles_loaded": len(candles),
            "hold_candles": hold,
        },
        "signal_source": {
            "key": f"v2:signals:paper:{symbol}:{timeframe}",
            "action": signal.get("action"),
            "confidence": signal.get("confidence"),
            "price_target_after_cost": signal.get("price_target_after_cost"),
        },
        "summary": bt["summary"],
        "equity_curve": bt["equity_curve"],
        "trades": bt["trades"],
    }

    _write_results(client, run_id, result)
    _clear_pending(client, run_id)

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
