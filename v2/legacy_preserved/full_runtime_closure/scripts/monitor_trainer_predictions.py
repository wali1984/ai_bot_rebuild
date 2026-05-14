#!/usr/bin/env python3
"""
Trainer Prediction Monitor — Summarized View

Shows one row per symbol with TF directions condensed inline,
the deconflicted MULTI consensus highlighted, target price, and move%.

Usage:
    python scripts/monitor_trainer_predictions.py
    python scripts/monitor_trainer_predictions.py --interval 15
"""

import os
import sys
import time
import json
import argparse
import logging
from datetime import datetime
from typing import Dict
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

logging.basicConfig(level=logging.WARNING,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.StreamHandler(),
                              logging.FileHandler(os.path.join(ROOT_DIR, 'logs', 'trainer_prediction_monitor.log'))])
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MAX_AGE = 1800

# ANSI helpers
G = "\033[32m"; R = "\033[31m"; Y = "\033[33m"; C = "\033[36m"; DIM = "\033[2m"; B = "\033[1m"; RST = "\033[0m"


def _col(text, color, width=0):
    """Pad plain text to width FIRST, then wrap with ANSI color."""
    s = str(text)
    if width > 0:
        s = s.rjust(width) if width > 0 else s
    return f"{color}{s}{RST}"


def _lcol(text, color, width=0):
    """Left-aligned colored cell."""
    s = str(text)
    if width > 0:
        s = s.ljust(width)
    return f"{color}{s}{RST}"


def _now_str():
    if EASTERN_TZ:
        return datetime.now(EASTERN_TZ).strftime('%Y-%m-%d %H:%M:%S EST')
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')


def _fmt_price(px, w=13):
    if px <= 0: return "—".rjust(w)
    if px >= 1000: s = f"${px:,.2f}"
    elif px >= 1: s = f"${px:.4f}"
    elif px >= 0.01: s = f"${px:.6f}"
    else: s = f"${px:.8f}"
    return s.rjust(w)


def _fmt_age(sec):
    if sec is None: return "?"
    sec = float(sec)
    if sec < 0: return "0s"
    if sec < 60: return f"{sec:.0f}s"
    if sec < 3600: return f"{sec/60:.0f}m"
    return f"{sec/3600:.1f}h"


def _sf(v, d=0.0):
    try:
        if v is None: return d
        if isinstance(v, (bytes, bytearray)): v = v.decode()
        return float(v)
    except Exception: return d


def _tf_cell(d, conf, w=7):
    """Fixed-width colored TF cell: pad plain text, then color."""
    d = (d or "").upper()
    if d == "LONG":
        plain = f"L{conf:.0%}".rjust(w)
        return f"{G}{plain}{RST}"
    if d == "SHORT":
        plain = f"S{conf:.0%}".rjust(w)
        return f"{R}{plain}{RST}"
    plain = "—".rjust(w)
    return f"{DIM}{plain}{RST}"


class Monitor:
    TFS = ['5m', '15m', '1h', '4h']

    def __init__(self, interval=30, max_age=MAX_AGE):
        self.interval = interval
        self.max_age = max_age
        self.r = redis.from_url(REDIS_URL, decode_responses=True)
        self._target_cache = {}
        try:
            from config import SYMBOLS
            self.symbols = SYMBOLS
        except Exception:
            self.symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']

    def _price(self, sym):
        try:
            raw = self.r.get(f"price:{sym}")
            if raw:
                d = json.loads(raw) if raw.startswith('{') else {"price": raw}
                p = float(d.get("price", 0))
                if p > 0: return p
        except Exception: pass
        return 0.0

    def _predictions(self):
        preds = defaultdict(dict)
        now = time.time()
        keys = self.r.keys("prediction:*")
        pipe = self.r.pipeline(transaction=False)
        kl = []
        for k in keys:
            if self.r.type(k) == 'hash':
                pipe.hgetall(k)
                kl.append(k)
        results = pipe.execute()

        for k, data in zip(kl, results):
            if not data: continue
            parts = k.split(":")
            if len(parts) < 3: continue
            sym, tf = parts[1], parts[2]
            if sym not in self.symbols: continue  # skip removed symbols
            ts = _sf(data.get("timestamp"))
            age = now - ts if ts > 0 else 9999
            if age > self.max_age: continue
            ppo_c = _sf(data.get("ppo_confidence"))
            preds[sym][tf] = {
                'dir': (data.get("direction") or "").upper(),
                'action': (data.get("action") or ""),
                'conf': _sf(data.get("confidence")),
                'ppo': ppo_c if ppo_c > 0 else _sf(data.get("confidence")),
                'pub': data.get("published", "0") == "1",
                'threshold_passed': data.get("threshold_passed", data.get("published", "0")) == "1",
                'why': data.get("why", ""),
                'age': age,
            }
        return preds

    def _proposals(self):
        props = {}
        targets = {}

        try:
            entries = self.r.xrevrange("wma:proposals", count=5000)
            for _, data in entries:
                try: d = json.loads(data.get("data", "{}"))
                except Exception: continue
                sym = d.get("symbol", "")
                if not sym: continue
                src = d.get("source_module", d.get("source", ""))
                meta = d.get("metadata", {}) or {}

                # Collect target price from ANY source — first non-zero wins per symbol
                if sym not in targets:
                    for key in ("target_price", "price_target", "trainer_target_price", "take_profit", "tp_price"):
                        for s in (d, meta):
                            try:
                                v = float(s.get(key, 0) or 0)
                                if v > 0: targets[sym] = v; break
                            except Exception: pass
                        if sym in targets: break

                if src == "trainer" and sym not in props:
                    props[sym] = {
                        "action": (d.get("action_name") or d.get("action") or "").upper(),
                        "conf": float(d.get("confidence") or 0),
                    }
        except Exception: pass

        # Fallback: check prediction:*:* hashes for price_target
        try:
            keys = self.r.keys("prediction:*")
            for k in keys:
                if self.r.type(k) != 'hash': continue
                parts = k.split(":")
                if len(parts) < 3: continue
                sym = parts[1]
                if sym in targets: continue
                d = self.r.hgetall(k)
                for fld in ("price_target", "target_price"):
                    try:
                        v = float(d.get(fld, 0) or 0)
                        if v > 0: targets[sym] = v; break
                    except Exception: pass
        except Exception: pass

        # Merge targets into props and update persistent cache
        for sym, tp in targets.items():
            self._target_cache[sym] = tp

        result = {}
        all_syms = set(list(props.keys()) + list(targets.keys()) + list(self._target_cache.keys()))
        for sym in all_syms:
            p = props.get(sym, {})
            tp = targets.get(sym, 0) or self._target_cache.get(sym, 0)
            result[sym] = {
                "target": tp,
                "action": p.get("action", ""),
                "conf": p.get("conf", 0),
            }
        return result

    def _status(self):
        parts = []
        try:
            raw = self.r.get("status:trainer")
            if raw:
                s = json.loads(raw)
                ts = float(s.get("timestamp", 0))
                age = (time.time()*1000 - ts)/1000 if ts > 1e12 else time.time() - ts if ts > 1e9 else 0
                parts.append(f"mode={s.get('mode','?')} loop={s.get('loop','?')} steps={s.get('total_timesteps',0):,} age={_fmt_age(age)}")
        except Exception: pass
        try:
            hb = self.r.get("heartbeat:trainer")
            if hb:
                h = json.loads(hb.replace("'", '"'))
                parts.append(f"hb={_fmt_age(time.time()-float(h.get('timestamp',0)))} ago")
        except Exception: pass
        return " | ".join(parts) if parts else "unknown"

    def display(self):
        preds = self._predictions()
        props = self._proposals()
        W = 130

        o = ["\033[2J\033[H"]  # clear screen
        o.append("=" * W)
        o.append(f"  {B}TRAINER PREDICTIONS{RST}  —  {_now_str()}")
        o.append(f"  {self._status()}")

        try:
            o.append(f"  Redis: proposals={self.r.xlen('wma:proposals')}  signals={self.r.xlen('signals:trading:primary')}")
        except Exception: pass

        n_total = sum(len(v) for v in preds.values())
        n_pub = sum(1 for s in preds.values() for p in s.values() if p.get('pub'))
        n_multi = sum(1 for s in preds.values() if 'multi' in s)
        n_long = sum(1 for s in preds.values() for p in s.values() if p.get('dir') == 'LONG')
        n_short = sum(1 for s in preds.values() for p in s.values() if p.get('dir') == 'SHORT')

        o.append(f"  Total: {n_total} preds | {n_pub} published | {n_multi} deconflicted | Bias: {_col(f'L:{n_long}', G)} {_col(f'S:{n_short}', R)}")
        o.append("=" * W)

        # Header — plain text, padded normally
        hdr = (
            f"  {'SYMBOL':<17}"
            f" {'CONSENSUS':>10}"
            f"  {'5m':>7}"
            f"  {'15m':>7}"
            f"  {'1h':>7}"
            f"  {'4h':>7}"
            f"  {'PRICE':>13}"
            f"  {'TARGET':>13}"
            f"  {'MOVE%':>8}"
            f"  {'AGE':>5}"
        )
        o.append(f"{B}{hdr}{RST}")
        o.append("  " + "-" * (W - 2))

        for sym in sorted(preds.keys()):
            sp = preds[sym]
            price = self._price(sym)
            prop = props.get(sym, {})
            target = prop.get("target", 0)

            # Consensus: MULTI preferred, else highest PPO-conf TF
            multi = sp.get('multi')
            if multi:
                cons_dir = multi['dir']
                cons_conf = multi.get('ppo', multi['conf'])
                cons_pub = multi['pub']
            else:
                best = max(sp.values(), key=lambda x: x.get('ppo', x['conf'])) if sp else None
                cons_dir = best['dir'] if best else "?"
                cons_conf = best.get('ppo', best['conf']) if best else 0
                cons_pub = best['pub'] if best else False

            # Consensus: pad plain text to 10 chars, then color
            cons_plain = f"{'L' if cons_dir == 'LONG' else 'S' if cons_dir == 'SHORT' else 'H'} {cons_conf:.0%}".rjust(10)
            if cons_dir == "LONG":
                cons_cell = f"{G}{B}{cons_plain}{RST}"
            elif cons_dir == "SHORT":
                cons_cell = f"{R}{B}{cons_plain}{RST}"
            else:
                cons_cell = f"{DIM}{cons_plain}{RST}"

            cons_thr = multi.get('threshold_passed', False) if multi else (best.get('threshold_passed', False) if best else False)
            pub_mark = f"{G}*{RST}" if cons_pub else (f"{Y}+{RST}" if cons_thr else " ")

            # Per-TF cells — show PPO conf (raw model output, not MASA-discounted)
            tf_cells = []
            for tf in self.TFS:
                p = sp.get(tf)
                if p:
                    tf_cells.append(_tf_cell(p['dir'], p.get('ppo', p['conf']), 7))
                else:
                    tf_cells.append(f"{DIM}{'—':>7}{RST}")

            # Move%: pad to 8 chars before coloring
            if price > 0 and target > 0:
                pct = ((target - price) / price) * 100
                move_plain = f"{pct:>+7.2f}%"
                move = f"{G if pct >= 0 else R}{move_plain}{RST}"
            else:
                move = f"{'—':>8}"

            # Age
            ages = [p['age'] for p in sp.values() if 'age' in p]
            fresh = _fmt_age(min(ages)).rjust(5) if ages else "?".rjust(5)

            o.append(
                f"  {sym:<17}"
                f"{pub_mark}{cons_cell}"
                f"  {tf_cells[0]}"
                f"  {tf_cells[1]}"
                f"  {tf_cells[2]}"
                f"  {tf_cells[3]}"
                f"  {_fmt_price(price, 13)}"
                f"  {_fmt_price(target, 13)}"
                f"  {move}"
                f"  {fresh}"
            )

        o.append("  " + "-" * (W - 2))
        o.append(f"  {_col('L', G)}=Long  {_col('S', R)}=Short  {_col('*', G)}=Published  {_col('+', Y)}=Threshold passed  CONSENSUS=deconflicted multi  %=confidence")
        o.append("=" * W)

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
                logger.error(f"Error: {e}")
                time.sleep(10)


def main():
    parser = argparse.ArgumentParser(description='Monitor trainer predictions (summarized)')
    parser.add_argument('--interval', type=int, default=15, help='Refresh interval (default: 15s)')
    parser.add_argument('--max-age', type=int, default=MAX_AGE, help=f'Max prediction age (default: {MAX_AGE}s)')
    args = parser.parse_args()
    Monitor(interval=args.interval, max_age=args.max_age).run()


if __name__ == "__main__":
    main()
