#!/usr/bin/env python3
"""
Trainer Price Predictions Monitor
===================================
Shows current price vs trainer-predicted target price for each symbol/TF,
with confidence, predicted direction, predicted return %, and move-to-target %.

Usage:
    python scripts/monitor_trainer_prices.py
    python scripts/monitor_trainer_prices.py --interval 10
    python scripts/monitor_trainer_prices.py --symbols ETHUSDT,SOLUSDT
"""

import os
import sys
import time
import json
import argparse
from datetime import datetime
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, ROOT_DIR)

import redis

try:
    import pytz
    EASTERN_TZ = pytz.timezone('America/New_York')
except ImportError:
    EASTERN_TZ = None

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MAX_AGE = 1800

# ANSI colors
G = "\033[32m"; R = "\033[31m"; Y = "\033[33m"; C = "\033[36m"
M = "\033[35m"; DIM = "\033[2m"; B = "\033[1m"; RST = "\033[0m"

TFS = ['5m', '15m', '1h', '4h', 'multi']


def _now_str():
    if EASTERN_TZ:
        return datetime.now(EASTERN_TZ).strftime('%Y-%m-%d %H:%M:%S EST')
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')


def _sf(v, d=0.0):
    try:
        if v is None:
            return d
        if isinstance(v, (bytes, bytearray)):
            v = v.decode()
        return float(v)
    except Exception:
        return d


def _pad(text, width, align='right'):
    """Pad plain text to width, THEN return it (color-safe)."""
    if align == 'right':
        return str(text).rjust(width)
    return str(text).ljust(width)


def _cpad(text, color, width, align='right'):
    """Pad plain text to width first, then wrap with ANSI color."""
    padded = _pad(text, width, align)
    return f"{color}{padded}{RST}"


def _fmt_price(px):
    if px <= 0:
        return "--"
    if px >= 1000:
        return f"${px:,.2f}"
    if px >= 1:
        return f"${px:.4f}"
    if px >= 0.01:
        return f"${px:.6f}"
    return f"${px:.8f}"


def _fmt_age(sec):
    if sec is None or sec < 0:
        return "?"
    if sec < 60:
        return f"{sec:.0f}s"
    if sec < 3600:
        return f"{sec / 60:.0f}m"
    return f"{sec / 3600:.1f}h"


def _dir_str(direction, w=6):
    d = (direction or "").upper()
    if d == "LONG":
        return _cpad("LONG", f"{G}{B}", w)
    if d == "SHORT":
        return _cpad("SHORT", f"{R}{B}", w)
    return _cpad("HOLD", DIM, w)


def _conf_str(conf, label="", w=6):
    s = f"{conf * 100:.0f}%"
    if label:
        s = f"{label}{s}"
    padded = s.rjust(w)
    if conf >= 0.75:
        return f"{G}{B}{padded}{RST}"
    if conf >= 0.55:
        return f"{Y}{padded}{RST}"
    return f"{DIM}{padded}{RST}"


def _pct_str(pct, w=8):
    s = f"{pct:+.2f}%".rjust(w)
    if pct > 0.5:
        return f"{G}{s}{RST}"
    if pct < -0.5:
        return f"{R}{s}{RST}"
    return f"{DIM}{s}{RST}"


class PriceMonitor:
    def __init__(self, interval=15, max_age=MAX_AGE, symbols_filter=None):
        self.interval = interval
        self.max_age = max_age
        self.symbols_filter = [s.upper() for s in symbols_filter] if symbols_filter else None
        self.r = redis.from_url(REDIS_URL, decode_responses=True)
        try:
            from config import SYMBOLS
            self.all_symbols = SYMBOLS
        except Exception:
            self.all_symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']

    def _price(self, sym):
        try:
            raw = self.r.get(f"price:{sym}")
            if raw:
                d = json.loads(raw) if raw.startswith('{') else {"price": raw}
                p = float(d.get("price", 0))
                if p > 0:
                    return p
        except Exception:
            pass
        return 0.0

    def _all_predictions(self):
        preds = defaultdict(dict)
        now = time.time()
        keys = self.r.keys("prediction:*")
        pipe = self.r.pipeline(transaction=False)
        valid_keys = []
        for k in keys:
            if self.r.type(k) == 'hash':
                pipe.hgetall(k)
                valid_keys.append(k)
        results = pipe.execute()

        for k, data in zip(valid_keys, results):
            if not data:
                continue
            parts = k.split(":")
            if len(parts) < 3:
                continue
            sym, tf = parts[1], parts[2]
            if sym not in self.all_symbols: continue  # skip removed symbols
            if self.symbols_filter and sym not in self.symbols_filter:
                continue
            ts = _sf(data.get("timestamp"))
            age = now - ts if ts > 0 else 9999
            if age > self.max_age:
                continue

            preds[sym][tf] = {
                'direction': (data.get("direction") or "").upper(),
                'action': data.get("action_name") or data.get("action") or "",
                'confidence': _sf(data.get("confidence")),
                'ppo_conf': _sf(data.get("ppo_confidence")),
                'masa_conf': _sf(data.get("masa_confidence")),
                'model_conf': _sf(data.get("model_confidence")),
                'price_target': _sf(data.get("price_target")),
                'price_target_pct': _sf(data.get("price_target_pct")),
                'price_target_dir': (data.get("price_target_direction") or "").upper(),
                'predicted_return': _sf(data.get("predicted_return")),
                'entry_price': _sf(data.get("entry_price")),
                'published': data.get("published", "0") == "1",
                'threshold_passed': data.get("threshold_passed", "0") == "1",
                'age': age,
            }
        return preds

    def _regime(self, sym):
        try:
            raw = self.r.get(f"regime:{sym}")
            if raw:
                d = json.loads(raw)
                return {
                    'regime': (d.get("market_regime") or d.get("move_regime") or "?").upper(),
                    'trend': (d.get("trend_direction") or "?").upper(),
                    'alignment': _sf(d.get("tf_alignment")),
                }
        except Exception:
            pass
        return None

    def display(self):
        preds = self._all_predictions()

        o = ["\033[2J\033[H"]
        o.append("=" * 140)
        o.append(f"  {B}TRAINER PRICE PREDICTIONS{RST}  |  {_now_str()}  |  {len(preds)} symbols")
        o.append("=" * 140)

        if not preds:
            o.append(f"  {DIM}No predictions found (check trainer status){RST}")
            o.append("=" * 140)
            print("\n".join(o))
            sys.stdout.flush()
            return

        for sym in sorted(preds.keys()):
            sp = preds[sym]
            current_price = self._price(sym)
            regime_info = self._regime(sym)

            regime_str = ""
            if regime_info:
                regime_str = (f"  {DIM}regime={regime_info['regime']}  "
                              f"trend={regime_info['trend']}  "
                              f"align={regime_info['alignment']:.0%}{RST}")

            o.append(f"  {C}{B}{sym}{RST}  Price: {B}{_fmt_price(current_price)}{RST}{regime_str}")

            # Fixed-width header
            hdr = (f"  {'TF':<7}"
                   f"{'DIR':<8}"
                   f"{'PPO':>6}"
                   f"{'MASA':>7}"
                   f"{'BLEND':>7}"
                   f"  {'ENTRY':>13}"
                   f"  {'TARGET':>13}"
                   f"  {'MOVE%':>8}"
                   f"  {'RET%':>8}"
                   f"  {'PUB':>4}"
                   f"  {'AGE':>5}")
            o.append(f"{B}{hdr}{RST}")
            o.append("  " + "-" * 96)

            for tf in TFS:
                p = sp.get(tf)
                if not p:
                    continue

                tf_label = f"  {'MULTI' if tf == 'multi' else tf:<7}"
                if tf == 'multi':
                    tf_label = f"  {M}{B}{'MULTI':<7}{RST}"

                dir_cell = _dir_str(p['direction'], 8)

                ppo_cell = _conf_str(p['ppo_conf'], w=6) if p['ppo_conf'] > 0 else _pad("--", 6)
                masa_cell = _conf_str(p['masa_conf'], w=7) if p['masa_conf'] > 0 else _pad("--", 7)
                blend_cell = _conf_str(p['confidence'], w=7)

                entry_cell = _pad(_fmt_price(p['entry_price']) if p['entry_price'] > 0 else "--", 13)
                target_cell = _pad(_fmt_price(p['price_target']) if p['price_target'] > 0 else "--", 13)

                if current_price > 0 and p['price_target'] > 0:
                    move_pct = ((p['price_target'] - current_price) / current_price) * 100
                    move_cell = _pct_str(move_pct, 8)
                else:
                    move_cell = _pad("--", 8)

                ret = p['predicted_return']
                ret_cell = _pct_str(ret, 8) if abs(ret) > 0.001 else _pad("--", 8)

                if p['published']:
                    pub_cell = f"{G}{'YES':>4}{RST}"
                elif p['threshold_passed']:
                    pub_cell = f"{Y}{'THR':>4}{RST}"
                else:
                    pub_cell = f"{DIM}{'no':>4}{RST}"

                age_cell = _pad(_fmt_age(p['age']), 5)

                o.append(f"{tf_label}"
                         f"{dir_cell}"
                         f"{ppo_cell}"
                         f"{masa_cell}"
                         f"{blend_cell}"
                         f"  {entry_cell}"
                         f"  {target_cell}"
                         f"  {move_cell}"
                         f"  {ret_cell}"
                         f"  {pub_cell}"
                         f"  {age_cell}")

            o.append("")

        o.append("  " + "-" * 96)
        o.append(f"  DIR: {G}{B}LONG{RST}  {R}{B}SHORT{RST}  |  "
                 f"MOVE%=target vs current  |  RET%=predicted return  |  "
                 f"{G}YES{RST}=published  {Y}THR{RST}=threshold")
        o.append("=" * 140)

        print("\n".join(o))
        sys.stdout.flush()

    def run(self):
        while True:
            try:
                self.display()
                time.sleep(self.interval)
            except KeyboardInterrupt:
                print("\nStopped.")
                break
            except Exception as e:
                import traceback
                traceback.print_exc()
                time.sleep(10)


def main():
    parser = argparse.ArgumentParser(description='Monitor trainer price predictions per TF')
    parser.add_argument('--interval', type=int, default=15, help='Refresh interval in seconds (default: 15)')
    parser.add_argument('--max-age', type=int, default=MAX_AGE, help=f'Max prediction age in seconds (default: {MAX_AGE})')
    parser.add_argument('--symbols', type=str, default=None, help='Comma-separated symbols to filter (e.g. ETHUSDT,SOLUSDT)')
    args = parser.parse_args()
    symbols = args.symbols.split(',') if args.symbols else None
    PriceMonitor(interval=args.interval, max_age=args.max_age, symbols_filter=symbols).run()


if __name__ == "__main__":
    main()
