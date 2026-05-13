#!/usr/bin/env python3
"""
ASJAD TRADER PORTFOLIO MONITOR (Enhanced)
==========================================
Real-time monitoring with:
  - Binance positions + Redis-enriched data
  - Stealth TP/SL levels & trailing stop status per position
  - Regime, trend, TF alignment per symbol
  - Trainer prediction consensus
  - Dynamic TP target
"""

import redis
import json
import time
import os
from datetime import datetime
from dotenv import load_dotenv
from typing import Any, Dict, List, Optional, Tuple

try:
    from binance.client import Client
    BINANCE_AVAILABLE = True
except ImportError:
    BINANCE_AVAILABLE = False
    Client = None

load_dotenv()

# ANSI
G = "\033[32m"; R = "\033[31m"; Y = "\033[33m"; C = "\033[36m"
M = "\033[35m"; DIM = "\033[2m"; B = "\033[1m"; RST = "\033[0m"
UL = "\033[4m"


def _sf(v, d=0.0):
    try:
        if v is None:
            return d
        if isinstance(v, (bytes, bytearray)):
            v = v.decode()
        return float(v)
    except Exception:
        return d


def _pad(text, w, align='r'):
    s = str(text)
    return s.rjust(w) if align == 'r' else s.ljust(w)


def _cpad(text, color, w, align='r'):
    return f"{color}{_pad(text, w, align)}{RST}"


def _fmt_px(px):
    if px <= 0:
        return "--"
    if px >= 1000:
        return f"{px:,.2f}"
    if px >= 1:
        return f"{px:,.4f}"
    if px >= 0.01:
        return f"{px:,.6f}"
    return f"{px:,.8f}"


def _fmt_age(sec):
    if sec is None or sec < 0:
        return "?"
    if sec < 60:
        return f"{sec:.0f}s"
    if sec < 3600:
        return f"{sec / 60:.0f}m"
    return f"{sec / 3600:.1f}h"


class AsjadPortfolioMonitor:
    def __init__(self):
        self.redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)
        self.account_id = "asjad"
        self.client = None
        self._last_mark_prices: Dict[str, float] = {}

        if not BINANCE_AVAILABLE:
            print("Warning: Binance library not available")
            return
        try:
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent))
            api_key = os.getenv("BINANCE_API_KEY_ASJAD") or os.getenv("BINANCE_API_KEY_BROTHER")
            api_secret = os.getenv("BINANCE_API_SECRET_ASJAD") or os.getenv("BINANCE_API_SECRET_BROTHER")
            if api_key and api_secret:
                self.client = Client(api_key=api_key, api_secret=api_secret)
        except Exception as e:
            print(f"Failed to init Binance: {e}")

    def run(self):
        while True:
            try:
                self._display()
                time.sleep(15)
            except KeyboardInterrupt:
                print("\nStopped.")
                break
            except Exception:
                import traceback; traceback.print_exc()
                time.sleep(5)

    # ── Binance data ───────────────────────────────────────────────
    def _fetch_account(self):
        if not self.client:
            return None
        try:
            return self.client.futures_account()
        except Exception:
            return None

    def _fetch_positions(self, account):
        if not self.client:
            return []
        try:
            positions = self.client.futures_position_information()
        except Exception:
            return []

        lev_map, be_map = {}, {}
        if account:
            for ap in account.get('positions', []) or []:
                sym = ap.get('symbol')
                if not sym:
                    continue
                try:
                    lev_map[sym] = int(float(ap.get('leverage', 1) or 1))
                except Exception:
                    lev_map[sym] = 1
                try:
                    be_map[sym] = float(ap.get('breakEvenPrice', 0) or 0)
                except Exception:
                    pass

        active = []
        for pos in positions:
            try:
                amt = float(pos.get('positionAmt', 0) or 0)
                if amt == 0:
                    continue
                sym = pos.get('symbol', '?')
                entry = float(pos.get('entryPrice', 0) or 0)
                mark = self._resolve_mark(sym, float(pos.get('markPrice', 0) or 0), entry)
                liq = float(pos.get('liquidationPrice', 0) or 0)
                pnl = float(pos.get('unRealizedProfit', 0) or 0)
                lev = lev_map.get(sym, int(float(pos.get('leverage', 1) or 1)))
                notional = abs(amt) * (mark if mark > 0 else entry)
                pim = float(pos.get('positionInitialMargin', 0) or 0)
                iso = float(pos.get('isolatedMargin', 0) or 0)
                mtype = (pos.get('marginType') or 'cross').lower()
                margin = pim if pim > 0 else (iso if mtype == 'isolated' and iso > 0 else (notional / lev if lev > 0 else notional))
                active.append({
                    "symbol": sym, "amt": amt,
                    "side": "LONG" if amt > 0 else "SHORT",
                    "lev": lev, "entry": entry, "be": be_map.get(sym, 0),
                    "mark": mark, "liq": liq, "margin": margin,
                    "maint": float(pos.get('maintMargin', 0) or 0),
                    "pnl": pnl, "notional": notional * (1 if amt > 0 else -1),
                    "mtype": mtype,
                })
            except Exception:
                continue
        active.sort(key=lambda p: abs(p.get("margin", 0)), reverse=True)
        return active

    def _resolve_mark(self, sym, mark, entry):
        if mark > 0:
            self._last_mark_prices[sym] = mark
            return mark
        try:
            raw = self.redis_client.get(f"latest:binance:mark_price:{sym}")
            if raw:
                px = float(json.loads(raw).get('mark_price', 0) or 0)
                if px > 0:
                    self._last_mark_prices[sym] = px
                    return px
        except Exception:
            pass
        return self._last_mark_prices.get(sym, entry) or entry

    def _margin_ratio(self, account):
        if not account:
            return None
        try:
            maint = float(account.get('totalMaintMargin', 0) or 0)
            mb = float(account.get('totalMarginBalance', 0) or 0)
            return (maint / mb) * 100 if mb > 0 else None
        except Exception:
            return None

    # ── Redis data ─────────────────────────────────────────────────
    def _stealth_stops(self):
        result = {}
        try:
            raw = self.redis_client.get(f"stealth_stops:{self.account_id}")
            if not raw:
                return result
            for s in json.loads(raw):
                key = f"{s.get('symbol', '')}:{s.get('side', '')}".upper()
                result.setdefault(key, []).append(s)
        except Exception:
            pass
        return result

    def _regime(self, sym):
        try:
            raw = self.redis_client.get(f"regime:{sym}")
            return json.loads(raw) if raw else None
        except Exception:
            return None

    def _prediction(self, sym):
        try:
            for tf in ('multi', '1h', '15m', '5m'):
                data = self.redis_client.hgetall(f"prediction:{sym}:{tf}")
                if not data:
                    continue
                if time.time() - _sf(data.get("timestamp")) > 1800:
                    continue
                return {
                    'dir': (data.get("direction") or "").upper(),
                    'conf': _sf(data.get("confidence")),
                    'target': _sf(data.get("price_target")),
                    'tf': tf,
                    'pub': data.get("published", "0") == "1",
                }
        except Exception:
            pass
        return None

    def _redis_pos(self, sym, side):
        try:
            raw = self.redis_client.hgetall(f"positions:live:{sym}")
            if not raw:
                return None
            blob = raw.get(side.lower())
            return json.loads(blob) if blob else None
        except Exception:
            return None

    # ── Display ────────────────────────────────────────────────────
    def _display(self):
        os.system('clear')
        W = 155
        acct = self._fetch_account()
        positions = self._fetch_positions(acct)
        mr = self._margin_ratio(acct)
        stealth = self._stealth_stops()

        print("=" * W)
        print(f"  {B}ASJAD PORTFOLIO MONITOR{RST}  |  Account: ASJAD  |  "
              f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * W)

        # ── Account summary ──
        if acct:
            wallet = float(acct.get('totalWalletBalance', 0) or 0)
            avail = float(acct.get('availableBalance', 0) or 0)
            pnl = float(acct.get('totalUnrealizedProfit', 0) or 0)
            maint = float(acct.get('totalMaintMargin', 0) or 0)
            pnl_pct = (pnl / wallet) * 100 if wallet > 0 else 0
            pc = G if pnl >= 0 else R
            mc = R if mr and mr > 50 else Y if mr and mr > 20 else G
            mr_s = f"{mr:.2f}%" if mr is not None else "--"
            print(f"  Wallet: {B}${wallet:,.2f}{RST}  "
                  f"Avail: ${avail:,.2f}  "
                  f"PnL: {pc}{B}${pnl:+,.2f}{RST} ({pc}{pnl_pct:+.2f}%{RST})  "
                  f"Margin Ratio: {mc}{mr_s}{RST}  "
                  f"Maint: ${maint:,.2f}")
        else:
            eq = self.redis_client.get(f"portfolio:equity:{self.account_id}")
            if eq:
                d = json.loads(eq)
                print(f"  {Y}[Redis]{RST} Equity: ${d.get('equity_usd',0):,.2f}  "
                      f"PnL: ${d.get('unrealized_pnl_usd',0):+,.2f}  "
                      f"Age: {_fmt_age(time.time() - d.get('timestamp', 0))}")

        # ── Stealth summary ──
        n_sl = sum(1 for ss in stealth.values() for s in ss if s.get('stop_type') == 'STOP_LOSS')
        n_tp = sum(1 for ss in stealth.values() for s in ss if s.get('stop_type') == 'TAKE_PROFIT')
        n_tr = sum(1 for ss in stealth.values() for s in ss if 'TRAIL' in str(s.get('reason', '')).upper())
        print(f"  Stealth: {n_sl} SL | {n_tp} TP | {n_tr} Trailing  |  "
              f"{len(positions)} positions")
        print("=" * W)

        if not positions:
            print(f"  {DIM}No active positions{RST}")
            print("=" * W)
            return

        # ── Position table ──
        hdr = (f"  {'Symbol':<13}"
               f" {'Side':<6}"
               f" {'Lev':>4}"
               f" {'Notional':>11}"
               f" {'Entry':>12}"
               f" {'Mark':>12}"
               f" {'Liq':>10}"
               f" {'Margin':>9}"
               f" {'PnL':>9}"
               f" {'ROI%':>7}"
               f" {'SthSL':>12}"
               f" {'SthTP':>12}"
               f" {'Trail':>5}")
        print(f"{B}{hdr}{RST}")
        print("  " + "-" * (W - 4))

        tot_margin = 0.0
        tot_pnl = 0.0

        for p in positions:
            sym = p['symbol']
            side = p['side']
            lev = p['lev']
            margin = p['margin']
            pnl = p['pnl']
            roi = (pnl / margin) * 100 if margin > 0 else 0
            tot_margin += margin
            tot_pnl += pnl

            key = f"{sym}:{side}"
            stops = stealth.get(key, [])
            sl_px = [s['trigger_price'] for s in stops
                     if s.get('stop_type') == 'STOP_LOSS'
                     and 'TRAIL' not in str(s.get('reason', '')).upper()]
            tp_px = [s['trigger_price'] for s in stops
                     if s.get('stop_type') == 'TAKE_PROFIT']
            has_trail = any('TRAIL' in str(s.get('reason', '')).upper() for s in stops)

            sc = G if side == "LONG" else R
            pc = G if pnl >= 0 else R

            sl_s = _pad(_fmt_px(max(sl_px)), 12) if sl_px else _pad("--", 12)
            tp_s = _pad(_fmt_px(min(tp_px)), 12) if tp_px else _pad("--", 12)
            tr_s = _cpad("ARM", G, 5) if has_trail else _pad("--", 5)

            not_s = f"{p['notional']:+,.0f}"
            ent_s = _fmt_px(p['entry'])
            mrk_s = _fmt_px(p['mark'])
            liq_s = _fmt_px(p['liq']) if p['liq'] > 0 else '--'
            mar_s = f"${margin:,.2f}"
            pnl_s = f"${pnl:+,.2f}"
            roi_s = f"{roi:+.1f}%"

            print(f"  {_pad(sym, 13, 'l')}"
                  f" {sc}{_pad(side, 6, 'l')}{RST}"
                  f" {_pad(f'{lev}x', 4)}"
                  f" {_pad(not_s, 11)}"
                  f" {_pad(ent_s, 12)}"
                  f" {_pad(mrk_s, 12)}"
                  f" {_pad(liq_s, 10)}"
                  f" {_pad(mar_s, 9)}"
                  f" {pc}{_pad(pnl_s, 9)}{RST}"
                  f" {pc}{_pad(roi_s, 7)}{RST}"
                  f" {sl_s}"
                  f" {tp_s}"
                  f" {tr_s}")

        print("  " + "-" * (W - 4))
        tot_roi = (tot_pnl / tot_margin) * 100 if tot_margin > 0 else 0
        tc = G if tot_pnl >= 0 else R
        print(f"  {_pad('TOTAL', 13, 'l')}"
              f" {_pad('', 6, 'l')}"
              f" {_pad('', 4)}"
              f" {_pad('', 11)}"
              f" {_pad('', 12)}"
              f" {_pad('', 12)}"
              f" {_pad('', 10)}"
              f" {_pad(f'${tot_margin:,.2f}', 9)}"
              f" {tc}{_pad(f'${tot_pnl:+,.2f}', 9)}{RST}"
              f" {tc}{_pad(f'{tot_roi:+.1f}%', 7)}{RST}")

        # ── Per-symbol detail ──
        print()
        print(f"  {B}{UL}PER-SYMBOL DETAIL{RST}")
        seen = set()
        for p in positions:
            sym = p['symbol']
            if sym in seen:
                continue
            seen.add(sym)

            regime = self._regime(sym)
            pred = self._prediction(sym)
            mark = p['mark']

            line = f"  {C}{B}{sym}{RST}  "

            if regime:
                rr = (regime.get('market_regime') or regime.get('move_regime') or '?').upper()
                td = (regime.get('trend_direction') or '?').upper()
                ta = _sf(regime.get('tf_alignment'))
                vs = _sf(regime.get('volatility_score'))
                rc = G if rr in ('TRENDING','TREND') else R if rr in ('VOLATILE','SQUEEZE') else C
                dc = G if td == 'LONG' else R if td == 'SHORT' else DIM
                line += (f"Regime:{rc}{rr}{RST}  "
                         f"Trend:{dc}{td}{RST}  "
                         f"Align:{ta:.0%}  "
                         f"Vol:{vs:.2f}")
            else:
                line += f"{DIM}no regime{RST}"

            if pred:
                pd = pred['dir']
                dc = G if pd == 'LONG' else R if pd == 'SHORT' else DIM
                pb = f"{G}PUB{RST}" if pred['pub'] else f"{DIM}---{RST}"
                move = ""
                if mark > 0 and pred['target'] > 0:
                    mv = ((pred['target'] - mark) / mark) * 100
                    mc = G if mv > 0 else R
                    move = f" Move:{mc}{mv:+.2f}%{RST}"
                line += (f"  |  Pred({pred['tf']}): {dc}{B}{pd}{RST} "
                         f"{pred['conf']:.0%} "
                         f"Tgt:{_fmt_px(pred['target'])}{move} {pb}")

            print(line)

            for side in ("LONG", "SHORT"):
                key = f"{sym}:{side}"
                stops = stealth.get(key, [])
                if not stops:
                    continue

                rp = self._redis_pos(sym, side)
                sc = G if side == "LONG" else R

                sl_stops = [s for s in stops if s.get('stop_type') == 'STOP_LOSS' and 'TRAIL' not in str(s.get('reason','')).upper()]
                tp_stops = [s for s in stops if s.get('stop_type') == 'TAKE_PROFIT']
                tr_stops = [s for s in stops if 'TRAIL' in str(s.get('reason','')).upper()]

                parts = [f"    {sc}{side}{RST}:"]
                if sl_stops:
                    parts.append(f"SL={','.join(_fmt_px(s['trigger_price']) for s in sl_stops)}")
                for tp in tp_stops:
                    cp = tp.get('close_percentage', 100)
                    parts.append(f"TP={_fmt_px(tp['trigger_price'])}({cp:.0f}%)")
                for ts in tr_stops:
                    parts.append(f"{Y}TRAIL={_fmt_px(ts['trigger_price'])}{RST} [{str(ts.get('reason',''))[:35]}]")
                if rp:
                    extras = []
                    age = _sf(rp.get('age_seconds'))
                    dtp = _sf(rp.get('take_profit'))
                    dsl = _sf(rp.get('stop_loss'))
                    if age > 0:
                        extras.append(f"age={_fmt_age(age)}")
                    if dtp > 0:
                        extras.append(f"dtp={_fmt_px(dtp)}")
                    if dsl > 0:
                        extras.append(f"dsl={_fmt_px(dsl)}")
                    if extras:
                        parts.append(f"{DIM}({' '.join(extras)}){RST}")

                print("  ".join(parts))

        print()
        print("=" * W)


if __name__ == "__main__":
    AsjadPortfolioMonitor().run()
