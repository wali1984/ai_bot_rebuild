# ProChart Specification — CoinAnk-Style Multi-Pane Trading Chart

**Audit reference:** Section 18 of `audit-website.md`  
**Written:** 2026-06-13 | Claude Code (Sonnet 4.6)  
**Goal:** Replicate CoinAnk proChart layout using our existing ingested data feeds.

---

## 1. What CoinAnk proChart Shows (Screenshot Analysis)

```
┌──────────────────────────────────────────────────────────────────┬──────────────────┐
│ HEADER BAR                                                       │ RIGHT PANEL      │
│ [BTCUSDT] [Binance] [1m][5m][15m][30m][1H][5m*] [Indicators]   │ [Favorite][Markets]│
├──────────────────────────────────────────────────────────────────│                  │
│ PANE 0 — Main Candlestick Chart (55% height)                    │ BTC  $64,070 +0.4%│
│   SMC order blocks (blue/pink rectangles)                        │ ETH  $1,676  +0.5%│
│   SuperTrend dots (above/below candles, red/green)              │ SOL  $68.22  +1.2%│
│   Liquidation level lines (dotted horizontal)                    │ LINK $8.019  +1.9%│
│   Liquidity heatmap (colored vertical bars on right)            │ XRP  $1.147  +1.5%│
│   BigLiquidation whale markers                                   │ LTC  $43.74  +1.5%│
│                                                                  │ LAB  $9.388  -7.2%│
├──────────────────────────────────────────────────────────────────│                  │
│ PANE 1 — Open Interest (15% height)                             │ ──────────────── │
│   Candle chart: OI kline (green up / red down)                  │ BTCUSDT Binance  │
│   H:4.14M O:4.14M L:4.14M C:4.14M                              │ $9.378 -7.37%    │
├──────────────────────────────────────────────────────────────────│                  │
│ PANE 2 — Net Long (15% height)                                  │ 24h High: 10.455 │
│   Histogram (green) H:72.49K                                    │ 24h Low:  9.060  │
├──────────────────────────────────────────────────────────────────│ Volume: $88.58M  │
│ PANE 3 — Net Short (15% height)                                 │ Funding: 0.0076% │
│   Histogram (red)   H:4.09K                                     │ MCap: $2.9B      │
├──────────────────────────────────────────────────────────────────│ OI: $139.11M    │
│ PANE 4 — Volume (histogram)                                     │ L/S (Account):.. │
└──────────────────────────────────────────────────────────────────┴──────────────────┘
```

---

## 2. Data Availability Map

| Data | Source | Status | Redis / File Location |
|---|---|---|---|
| OHLCV candles per symbol+timeframe | Binance public stream plus public REST candle backfill | REALTIME OR CURRENT | WebSocket frames are realtime when received; public REST backfill is current or stale based on freshness. |
| Volume histogram | Same candle source | REALTIME OR CURRENT | Derived from the same stream/current candle source and must carry source/freshness state. |
| SMA20, EMA20/50, BB, price_target | Typed indicator contract or disabled control | SOURCE-LABELED | Static chart-file overlays are withheld from primary realtime controls unless current indicator evidence exists. |
| AI signal (direction, target, confidence) | Typed signal contract | SOURCE-LABELED | Signal overlays require source/freshness and trader scope; missing signals render disabled states. |
| 100+ symbols × 5 timeframes | Chart manifest / market overview contract | SOURCE-LABELED | Manifest and overview rows must show source/freshness and missing-source state. |
| Open Interest kline (per symbol) | CoinAnk-derived backend adapter when wired | SOURCE PENDING | Redis source must be exposed through typed API with freshness before being shown as current. |
| Net Long / Short kline | CoinAnk-derived backend adapter when wired | SOURCE PENDING | Redis source must be exposed through typed API with freshness before being shown as current. |
| Funding Rate kline | CoinAnk-derived backend adapter when wired | SOURCE PENDING | Redis source must be exposed through typed API with freshness before being shown as current. |
| Long/Short Ratio kline | CoinAnk-derived backend adapter when wired | SOURCE PENDING | Redis source must be exposed through typed API with freshness before being shown as current. |
| Liquidation history (per symbol) | CoinAnk-derived backend adapter when wired | SOURCE PENDING | Redis source must be exposed through typed API with freshness before being shown as current. |
| Liquidation heatmap | CoinAnk-derived backend adapter when wired | SOURCE PENDING | Redis source must be exposed through typed API with freshness before being shown as current. |
| Large orders / whale trades | CoinAnk-derived backend adapter when wired | SOURCE PENDING | Redis source must be exposed through typed API with freshness before being shown as current. |
| CVD (cumulative volume delta) | CoinAnk-derived backend adapter when wired | SOURCE PENDING | Redis source must be exposed through typed API with freshness before being shown as current. |
| Buy/Sell Volume | CoinAnk-derived backend adapter when wired | SOURCE PENDING | Redis source must be exposed through typed API with freshness before being shown as current. |
| SMC indicator (order blocks) | CoinAnk-derived backend adapter when wired | SOURCE PENDING | Redis source must be exposed through typed API with freshness before being shown as current. |
| Market Cap | CoinAnk-derived backend adapter when wired | SOURCE PENDING | Redis source must be exposed through typed API with freshness before being shown as current. |
| Global fear/greed, OI, vol | CoinAnk-derived backend adapter when wired | SOURCE PENDING | Redis source must be exposed through typed API with freshness before being shown as current. |

**CoinAnk ingestor confirmed running at:** `https://open-api.coinank.com` (40+ endpoints)  
**Security note:** Frontend must NEVER call CoinAnk API directly. Data flows:

```text
CoinAnk API → legacy_reference/ingest/live_coinank.py → Redis → FastAPI → Frontend
```

---

## 3. New Backend Endpoint — `/api/v1/chart/coinank/{symbol}/{timeframe}`

**New file:** `v2/backend/app/api/v1/chart.py`

```py
# chart.py — serves CoinAnk overlay data for ProChart sub-panels
from fastapi import APIRouter, Query
import redis, json, os

router = APIRouter(prefix="/chart", tags=["chart"])

def _get_redis():
    return redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)

def _read_coinank_key(r, key_pattern: str):
    keys = r.keys(key_pattern)
    if not keys:
        return None
    raw = r.get(sorted(keys)[-1])
    return json.loads(raw) if raw else None

def _normalize_kline_series(raw_data) -> list[dict]:
    """Convert CoinAnk kline response to [{time: UTC_seconds, value: float}]."""
    if not raw_data:
        return []
    if isinstance(raw_data, dict):
        raw_data = raw_data.get('data') or raw_data.get('list') or raw_data.get('klineList') or []
    if not isinstance(raw_data, list):
        return []
    series = []
    for row in raw_data:
        if isinstance(row, (list, tuple)) and len(row) >= 5:
            try:
                series.append({"time": int(row[0]) // 1000, "value": float(row[4])})
            except (ValueError, TypeError):
                pass
        elif isinstance(row, dict):
            ts = row.get('time') or row.get('t') or row.get('timestamp')
            val = row.get('value') or row.get('close') or row.get('c') or row.get('v')
            if ts and val is not None:
                try:
                    ts_sec = int(ts) // 1000 if int(ts) > 1e10 else int(ts)
                    series.append({"time": ts_sec, "value": float(val)})
                except (ValueError, TypeError):
                    pass
    return sorted(series, key=lambda x: x['time'])

@router.get("/coinank/{symbol}/{timeframe}")
async def get_coinank_overlay(
    symbol: str,
    timeframe: str,
    exchange: str = Query(default="Binance"),
) -> dict:
    r = _get_redis()
    exchange_lower = exchange.lower()
    sym_lower = symbol.lower()

    oi_kline = _normalize_kline_series(
        _read_coinank_key(r, f"v2:coinank:openInterest_kline:*{exchange_lower}*{sym_lower}*{timeframe}*")
    )
    net_long = _normalize_kline_series(
        _read_coinank_key(r, f"v2:coinank:netPositions_getNetPositions:*{exchange_lower}*{sym_lower}*{timeframe}*")
    )
    funding_kline = _normalize_kline_series(
        _read_coinank_key(r, f"v2:coinank:fundingRate_kline:*{exchange_lower}*{sym_lower}*{timeframe}*")
    )
    ls_kline = _normalize_kline_series(
        _read_coinank_key(r, f"v2:coinank:ls_kline:*{exchange_lower}*{sym_lower}*{timeframe}*")
    )
    cvd = _normalize_kline_series(
        _read_coinank_key(r, f"v2:coinank:marketOrder_getCvd:*{exchange_lower}*{sym_lower}*{timeframe}*")
    )

    market_cap_raw  = _read_coinank_key(r, f"v2:coinank:instruments_getCoinMarketCap:*{symbol.replace('USDT','').lower()}*")
    oi_all_raw      = _read_coinank_key(r, f"v2:coinank:openInterest_all:*{sym_lower}*")
    ls_rt_raw       = _read_coinank_key(r, f"v2:coinank:ls_exchange_realtimeAll:*{sym_lower}*")
    fund_cur_raw    = _read_coinank_key(r, f"v2:coinank:fundingRate_current:*")
    fg_raw          = r.get("features:global_coinank:fear_greed:latest")

    def _sf(d, *keys):
        for k in keys:
            v = (d or {}).get(k)
            try: return float(v)
            except: pass
        return None

    return {
        "symbol": symbol, "timeframe": timeframe, "exchange": exchange,
        "oi_kline": oi_kline,
        "net_long": net_long,
        "funding_kline": funding_kline,
        "ls_kline": ls_kline,
        "cvd": cvd,
        "stats": {
            "market_cap":   _sf(market_cap_raw, "marketCap", "market_cap"),
            "total_oi":     _sf(oi_all_raw,     "openInterest", "oi", "total"),
            "ls_ratio":     _sf(ls_rt_raw,       "ratio", "longShortRatio"),
            "funding_rate": _sf(fund_cur_raw,    "fundingRate", "rate"),
            "fear_greed":   json.loads(fg_raw)["value"] if fg_raw else None,
        },
    }


@router.get("/symbols")
async def get_chart_symbols() -> dict:
    """Returns all available symbols with current price for the watchlist."""
    import pathlib
    manifest_path = (
        pathlib.Path(__file__).parents[4]
        / "frontend/public/operator_runtime/v2_professional_market_chart/latest/operator_dashboard_payload.json"
    )
    try:
        manifest = json.loads(manifest_path.read_text())
        rows = [
            {
                "symbol": row.get("symbol"),
                "price":  row.get("latest_close"),
                "signal": row.get("signal_action"),
                "source_age_s": row.get("source_event_age_seconds"),
            }
            for row in (manifest.get("payloads") or {}).values()
            if row.get("symbol") and row.get("timeframe") == "5m"
        ]
        return {"symbols": rows, "count": len(rows)}
    except Exception as e:
        return {"symbols": [], "error": str(e)}
```

**Register in `v2/backend/app/main.py`:**
```py
from app.api.v1 import chart as chart_module
app.include_router(chart_module.router, prefix="/api/v1")
```

---

## 4. New Files to Create

```
v2/frontend/src/components/charts/
├── ProChart.tsx              ← NEW — main multi-pane chart component
├── ProChartSymbolPanel.tsx   ← NEW — right-side watchlist + stats
└── V2ProfessionalMarketChart.tsx ← EXISTING — keep, minor color update

v2/frontend/src/pages/
└── pro-chart/
    └── index.tsx             ← NEW — ProChart page at /chart/:symbol
```

---

## 5. ProChart Component

```tsx
// v2/frontend/src/components/charts/ProChart.tsx

import { useEffect, useRef, useState, useCallback } from 'react';
import {
  createChart, CandlestickSeries, HistogramSeries, LineSeries,
  ColorType, LineStyle,
  type IChartApi, type ISeriesApi, type UTCTimestamp,
} from 'lightweight-charts';
import { usePayloadFile } from '../../hooks/usePayloadFile';

// ─── Types ───────────────────────────────────────────────────────────────────

interface ProChartProps {
  symbol: string;
  timeframe: string;
  exchange?: string;
  height?: number;
}

interface CoinAnkOverlay {
  oi_kline:      Array<{time: number; value: number}>;
  net_long:      Array<{time: number; value: number}>;
  funding_kline: Array<{time: number; value: number}>;
  ls_kline:      Array<{time: number; value: number}>;
  cvd:           Array<{time: number; value: number}>;
  stats: {
    market_cap:   number | null;
    total_oi:     number | null;
    ls_ratio:     number | null;
    funding_rate: number | null;
    fear_greed:   number | null;
  };
}

// ─── Color tokens ────────────────────────────────────────────────────────────
const C = {
  buy:      '#00d4a3',
  sell:     '#f6465d',
  ai:       '#6c63ff',
  buyDim:   'rgba(0,212,163,0.22)',
  sellDim:  'rgba(246,70,93,0.22)',
  oiUp:     'rgba(0,212,163,0.60)',
  oiDown:   'rgba(246,70,93,0.60)',
  netLong:  'rgba(0,212,163,0.70)',
  netShort: 'rgba(246,70,93,0.70)',
  bg:       '#0a0e14',
  grid:     'rgba(255,255,255,0.04)',
  text:     '#7d8fa8',
  border:   'rgba(255,255,255,0.06)',
};

// ─── Component ───────────────────────────────────────────────────────────────

export function ProChart({ symbol, timeframe, exchange = 'Binance', height = 700 }: ProChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef     = useRef<IChartApi | null>(null);

  // Series refs — pane 0 (main)
  const candleRef  = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volRef     = useRef<ISeriesApi<'Histogram'>   | null>(null);
  const ema20Ref   = useRef<ISeriesApi<'Line'>        | null>(null);
  const ema50Ref   = useRef<ISeriesApi<'Line'>        | null>(null);
  const bbUpperRef = useRef<ISeriesApi<'Line'>        | null>(null);
  const bbLowerRef = useRef<ISeriesApi<'Line'>        | null>(null);
  const targetRef  = useRef<ISeriesApi<'Line'>        | null>(null);

  // Series refs — pane 1 (OI), pane 2 (L/S)
  const oiRef       = useRef<ISeriesApi<'Histogram'> | null>(null);
  const netLongRef  = useRef<ISeriesApi<'Histogram'> | null>(null);
  const netShortRef = useRef<ISeriesApi<'Histogram'> | null>(null);

  // Indicator visibility state
  const [showOI,  setShowOI]  = useState(true);
  const [showLS,  setShowLS]  = useState(true);
  const [showBB,  setShowBB]  = useState(false);
  const [showEMA, setShowEMA] = useState(true);
  const [showAI,  setShowAI]  = useState(true);

  // OHLCV data (existing payload files, polled at 5s)
  const chartPath = `/operator_runtime/v2_professional_market_chart/latest/${symbol}_${timeframe}_chart.json`;
  const { data: chartPayload } = usePayloadFile(chartPath, 5_000);

  // CoinAnk overlay data (new backend endpoint, polled at 30s)
  const [overlay, setOverlay] = useState<CoinAnkOverlay | null>(null);
  const fetchOverlay = useCallback(async () => {
    try {
      const res = await fetch(`/api/v1/chart/coinank/${symbol}/${timeframe}?exchange=${exchange}`);
      if (res.ok) setOverlay(await res.json());
    } catch { /* silent */ }
  }, [symbol, timeframe, exchange]);

  useEffect(() => {
    fetchOverlay();
    const id = setInterval(fetchOverlay, 30_000);
    return () => clearInterval(id);
  }, [fetchOverlay]);

  // ─── Chart initialization ─────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width:  containerRef.current.clientWidth,
      height: height,
      layout: {
        background: { type: ColorType.Solid, color: C.bg },
        textColor: C.text,
        fontSize: 11,
        fontFamily: "'JetBrains Mono', 'IBM Plex Mono', monospace",
      },
      grid: {
        vertLines: { color: C.grid },
        horzLines: { color: C.grid },
      },
      crosshair: {
        vertLine: { color: 'rgba(255,255,255,0.2)', labelBackgroundColor: '#1a2230' },
        horzLine: { color: 'rgba(255,255,255,0.2)', labelBackgroundColor: '#1a2230' },
      },
      rightPriceScale: { borderColor: C.border, scaleMargins: { top: 0.05, bottom: 0.1 } },
      timeScale: {
        borderColor: C.border,
        timeVisible: true,
        secondsVisible: timeframe === '1m',
      },
    });

    // Pane 0: Candlestick
    candleRef.current = chart.addSeries(CandlestickSeries, {
      upColor: C.buy, downColor: C.sell,
      borderUpColor: C.buy, borderDownColor: C.sell,
      wickUpColor: C.buy, wickDownColor: C.sell,
    });

    // Pane 0: Volume (secondary scale, pinned to bottom)
    volRef.current = chart.addSeries(HistogramSeries, {
      priceScaleId: 'volume', priceFormat: { type: 'volume' },
    });
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

    // Pane 0: EMA20
    ema20Ref.current = chart.addSeries(LineSeries, {
      color: '#f59e0b', lineWidth: 1, lineStyle: LineStyle.Solid,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });

    // Pane 0: EMA50
    ema50Ref.current = chart.addSeries(LineSeries, {
      color: '#3b82f6', lineWidth: 1, lineStyle: LineStyle.Solid,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });

    // Pane 0: BB Upper/Lower
    const bbOpts = { color: 'rgba(108,99,255,0.5)', lineWidth: 1 as const, lineStyle: LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false };
    bbUpperRef.current = chart.addSeries(LineSeries, bbOpts);
    bbLowerRef.current = chart.addSeries(LineSeries, bbOpts);

    // Pane 0: AI target line
    targetRef.current = chart.addSeries(LineSeries, {
      color: C.ai, lineWidth: 1, lineStyle: LineStyle.Dotted,
      priceLineVisible: true, lastValueVisible: true,
    });

    // Pane 1: OI Histogram
    // NOTE: lightweight-charts v5 — pass { pane: 1 } to addSeries() to create a new pane.
    // If the API is different, use chart.addPane() explicitly first.
    oiRef.current = chart.addSeries(HistogramSeries, {
      color: C.oiUp,
      pane: 1,
    } as Parameters<typeof chart.addSeries>[1]);

    // Pane 2: Net Long / Short Histograms
    netLongRef.current  = chart.addSeries(HistogramSeries, { color: C.netLong,  pane: 2 } as any);
    netShortRef.current = chart.addSeries(HistogramSeries, { color: C.netShort, pane: 2 } as any);

    chartRef.current = chart;

    const ro = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    ro.observe(containerRef.current);

    return () => { ro.disconnect(); chart.remove(); chartRef.current = null; };
  // Recreate chart when timeframe changes (tick formatter update)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height, timeframe]);

  // ─── OHLCV data update ────────────────────────────────────────────────────
  useEffect(() => {
    if (!chartPayload || chartPayload.status !== 'CURRENT') return;

    const toTS = (t: number) => t as UTCTimestamp;

    if (candleRef.current && chartPayload.candles?.length) {
      candleRef.current.setData(
        [...chartPayload.candles]
          .filter(c => c.time && c.open && c.high && c.low && c.close)
          .map(c => ({ time: toTS(c.time), open: c.open!, high: c.high!, low: c.low!, close: c.close! }))
          .sort((a, b) => Number(a.time) - Number(b.time))
      );
    }

    if (volRef.current && chartPayload.volume?.length) {
      const byTime = new Map((chartPayload.candles ?? []).map(c => [c.time, c]));
      volRef.current.setData(
        [...chartPayload.volume]
          .filter(v => v.time !== undefined && v.value !== undefined)
          .map(v => ({
            time: toTS(v.time),
            value: v.value!,
            color: (byTime.get(v.time)?.close ?? 0) >= (byTime.get(v.time)?.open ?? 0) ? C.buyDim : C.sellDim,
          }))
          .sort((a, b) => Number(a.time) - Number(b.time))
      );
    }

    const ov = chartPayload.overlays ?? {};
    const toS = (arr: any[] | undefined) =>
      (arr ?? []).filter(p => p.time !== undefined && p.value !== null && p.value !== undefined)
                 .map(p => ({ time: toTS(p.time), value: p.value }))
                 .sort((a: any, b: any) => Number(a.time) - Number(b.time));

    if (ema20Ref.current)  ema20Ref.current.setData(showEMA ? toS(ov.ema20)     : []);
    if (ema50Ref.current)  ema50Ref.current.setData(showEMA ? toS(ov.emo50)     : []);
    if (bbUpperRef.current) bbUpperRef.current.setData(showBB ? toS(ov.bb_upper) : []);
    if (bbLowerRef.current) bbLowerRef.current.setData(showBB ? toS(ov.bb_lower) : []);

    const targetVal = chartPayload.signal?.target_line_value;
    const lastCandle = (chartPayload.candles ?? []).slice(-1)[0];
    if (targetRef.current && showAI && targetVal && lastCandle) {
      targetRef.current.setData([{ time: toTS(lastCandle.time), value: targetVal }]);
    }

    chartRef.current?.timeScale().fitContent();
  }, [chartPayload, showBB, showEMA, showAI]);

  // ─── CoinAnk overlay update ───────────────────────────────────────────────
  useEffect(() => {
    if (!overlay) return;

    const toHist = (arr: Array<{time: number; value: number}>, color: string) =>
      arr.filter(p => p.time && p.value !== undefined)
         .map(p => ({ time: p.time as UTCTimestamp, value: p.value, color }))
         .sort((a, b) => Number(a.time) - Number(b.time));

    if (oiRef.current && showOI && overlay.oi_kline?.length) {
      const data = toHist(overlay.oi_kline, C.oiUp);
      for (let i = 1; i < data.length; i++) {
        data[i].color = data[i].value >= data[i-1].value ? C.oiUp : C.oiDown;
      }
      oiRef.current.setData(data);
    }

    if (netLongRef.current  && showLS && overlay.net_long?.length) {
      netLongRef.current.setData(toHist(overlay.net_long, C.netLong));
    }
    if (netShortRef.current && showLS && overlay.net_long?.length) {
      const neg = overlay.net_long.map(p => ({ ...p, value: -Math.abs(p.value) }));
      netShortRef.current.setData(toHist(neg, C.netShort));
    }
  }, [overlay, showOI, showLS]);

  // ─── Signal badge ─────────────────────────────────────────────────────────
  const sig = chartPayload?.signal;
  const sigDir = sig?.selected_action?.includes('BUY') ? 'LONG'
               : sig?.selected_action?.includes('SELL') ? 'SHORT' : null;
  const conf = sig?.confidence_calibrated;

  return (
    <div className="prochart">
      <div className="prochart__controls">
        <button className={`prochart__toggle ${showEMA ? 'active' : ''}`} onClick={() => setShowEMA(v => !v)}>EMA</button>
        <button className={`prochart__toggle ${showBB  ? 'active' : ''}`} onClick={() => setShowBB(v  => !v)}>BB</button>
        <button className={`prochart__toggle ${showAI  ? 'active' : ''}`} onClick={() => setShowAI(v  => !v)}>AI Target</button>
        <span className="prochart__divider" />
        <button className={`prochart__toggle ${showOI  ? 'active' : ''}`} onClick={() => setShowOI(v  => !v)}>OI</button>
        <button className={`prochart__toggle ${showLS  ? 'active' : ''}`} onClick={() => setShowLS(v  => !v)}>L/S</button>
        {sigDir && conf && (
          <div className={`prochart__signal prochart__signal--${sigDir.toLowerCase()}`}>
            {sigDir} {(conf * 100).toFixed(0)}%
          </div>
        )}
      </div>
      <div ref={containerRef} className="prochart__canvas" style={{ height }} />
      {overlay?.stats && (
        <div className="prochart__stats">
          {overlay.stats.total_oi  != null && <span>OI: <strong>${(overlay.stats.total_oi/1e6).toFixed(2)}M</strong></span>}
          {overlay.stats.ls_ratio  != null && (
            <span>L/S: <strong className={overlay.stats.ls_ratio > 1 ? 'text-buy' : 'text-sell'}>{overlay.stats.ls_ratio.toFixed(2)}</strong></span>
          )}
          {overlay.stats.funding_rate != null && (
            <span>Funding: <strong className={overlay.stats.funding_rate > 0 ? 'text-buy' : 'text-sell'}>{(overlay.stats.funding_rate * 100).toFixed(4)}%</strong></span>
          )}
          {overlay.stats.market_cap  != null && <span>MCap: <strong>${(overlay.stats.market_cap/1e9).toFixed(2)}B</strong></span>}
          {overlay.stats.fear_greed  != null && <span>F&G: <strong>{overlay.stats.fear_greed.toFixed(0)}</strong></span>}
        </div>
      )}
    </div>
  );
}
```

---

## 6. Symbol Watchlist Panel

```tsx
// v2/frontend/src/components/charts/ProChartSymbolPanel.tsx

import { useState, useEffect } from 'react';

interface WatchlistSymbol {
  symbol: string;
  price: number | null;
  signal: string | null;
  source_age_s: number | null;
}

const FAVORITES = ['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT','LINKUSDT','LTCUSDT','AVAXUSDT'];

export function ProChartSymbolPanel({
  activeSymbol,
  onSymbolSelect,
}: {
  activeSymbol: string;
  onSymbolSelect: (s: string) => void;
}) {
  const [search, setSearch] = useState('');
  const [tab, setTab] = useState<'fav' | 'all'>('fav');
  const [symbols, setSymbols] = useState<WatchlistSymbol[]>([]);

  useEffect(() => {
    const load = () => fetch('/api/v1/chart/symbols').then(r => r.json()).then(d => setSymbols(d.symbols ?? [])).catch(() => {});
    load();
    const id = setInterval(load, 10_000);
    return () => clearInterval(id);
  }, []);

  const bySymbol = new Map(symbols.map(s => [s.symbol, s]));
  const filtered = (tab === 'fav'
    ? FAVORITES.map(s => bySymbol.get(s)).filter(Boolean) as WatchlistSymbol[]
    : symbols
  ).filter(s => s.symbol.toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="symbol-panel">
      <div className="symbol-panel__tabs">
        <button className={tab === 'fav' ? 'active' : ''} onClick={() => setTab('fav')}>Favorites</button>
        <button className={tab === 'all' ? 'active' : ''} onClick={() => setTab('all')}>Markets</button>
      </div>
      <div className="symbol-panel__search">
        <input type="text" placeholder="Search..." value={search} onChange={e => setSearch(e.target.value)} />
      </div>
      <div className="symbol-panel__list">
        {filtered.map(s => {
          const dir = s.signal?.includes('BUY') ? 'buy' : s.signal?.includes('SELL') ? 'sell' : null;
          return (
            <button key={s.symbol} className={`symbol-row ${s.symbol === activeSymbol ? 'symbol-row--active' : ''}`} onClick={() => onSymbolSelect(s.symbol)}>
              <span className="symbol-row__name">{s.symbol.replace('USDT','')}</span>
              <div className="symbol-row__right">
                <span className="symbol-row__price">
                  {s.price !== null ? `$${s.price?.toLocaleString('en-US', { maximumFractionDigits: 4 })}` : '—'}
                </span>
                {dir && <span className={`symbol-row__sig symbol-row__sig--${dir}`}>{dir === 'buy' ? '▲' : '▼'}</span>}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
```

---

## 7. ProChart Page

```tsx
// v2/frontend/src/pages/pro-chart/index.tsx
// Route: /chart  and  /chart/:symbol

import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ProChart } from '../../components/charts/ProChart';
import { ProChartSymbolPanel } from '../../components/charts/ProChartSymbolPanel';

const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h'] as const;
type TF = typeof TIMEFRAMES[number];

export default function ProChartPage() {
  const { symbol: routeSymbol } = useParams<{ symbol?: string }>();
  const navigate = useNavigate();
  const [symbol, setSymbol] = useState(routeSymbol?.toUpperCase() ?? 'BTCUSDT');
  const [timeframe, setTimeframe] = useState<TF>('5m');

  const handleSelect = (sym: string) => {
    setSymbol(sym);
    navigate(`/chart/${sym}`, { replace: true });
  };

  return (
    <div className="pro-chart-page">
      <div className="pro-chart-header">
        <div className="pro-chart-header__symbol">
          <span className="pro-chart-header__name">{symbol}</span>
          <span className="pro-chart-header__exchange">Binance SWAP</span>
        </div>
        <div className="pro-chart-header__timeframes">
          {TIMEFRAMES.map(tf => (
            <button key={tf} className={`tf-btn ${timeframe === tf ? 'tf-btn--active' : ''}`} onClick={() => setTimeframe(tf)}>
              {tf}
            </button>
          ))}
        </div>
      </div>
      <div className="pro-chart-layout">
        <div className="pro-chart-main">
          <ProChart
            symbol={symbol}
            timeframe={timeframe}
            height={typeof window !== 'undefined' ? window.innerHeight - 160 : 600}
          />
        </div>
        <div className="pro-chart-sidebar">
          <ProChartSymbolPanel activeSymbol={symbol} onSymbolSelect={handleSelect} />
        </div>
      </div>
    </div>
  );
}
```

**Add to router:**
```tsx
{ path: '/chart',         element: <ProChartPage /> },
{ path: '/chart/:symbol', element: <ProChartPage /> },
```

---

## 8. CSS

Add to `v2/frontend/src/styles.css` (or a new `pro-chart.css`):

```css
/* ── Pro Chart Page ── */
.pro-chart-page {
  display: flex; flex-direction: column;
  height: calc(100vh - 136px);
  overflow: hidden; background: var(--bg-base, #080c10);
}
.pro-chart-header {
  height: 44px; display: flex; align-items: center; gap: 16px;
  padding: 0 12px;
  background: var(--bg-panel, #0d1117);
  border-bottom: 1px solid var(--border, rgba(255,255,255,0.06));
  flex-shrink: 0;
}
.pro-chart-header__name  { font-size: 15px; font-weight: 700; color: var(--text-primary, #e4ebf5); }
.pro-chart-header__exchange { font-size: 11px; color: var(--text-muted, #4a5568); margin-left: 6px; }
.pro-chart-layout { display: flex; flex: 1; overflow: hidden; }
.pro-chart-main   { flex: 1; overflow: hidden; }
.pro-chart-sidebar { width: 280px; flex-shrink: 0; border-left: 1px solid var(--border, rgba(255,255,255,0.06)); overflow-y: auto; background: var(--bg-panel, #0d1117); }

/* ── Timeframe Buttons ── */
.tf-btn { padding: 3px 10px; font-size: 12px; font-weight: 500; color: var(--text-secondary, #7d8fa8); background: transparent; border: 1px solid transparent; border-radius: 4px; cursor: pointer; transition: all 80ms; }
.tf-btn:hover { color: var(--text-primary, #e4ebf5); background: rgba(255,255,255,0.05); }
.tf-btn--active { color: var(--buy, #00d4a3); border-color: var(--buy, #00d4a3); background: rgba(0,212,163,0.08); }

/* ── ProChart ── */
.prochart { display: flex; flex-direction: column; height: 100%; }
.prochart__controls {
  display: flex; align-items: center; gap: 6px; padding: 4px 8px;
  background: var(--bg-panel, #0d1117);
  border-bottom: 1px solid var(--border, rgba(255,255,255,0.06));
  height: 32px; flex-shrink: 0;
}
.prochart__toggle { padding: 2px 8px; font-size: 11px; font-weight: 500; color: var(--text-secondary, #7d8fa8); background: transparent; border: 1px solid rgba(255,255,255,0.08); border-radius: 3px; cursor: pointer; }
.prochart__toggle.active { color: var(--text-primary, #e4ebf5); border-color: rgba(255,255,255,0.2); background: rgba(255,255,255,0.05); }
.prochart__divider { width: 1px; height: 16px; background: rgba(255,255,255,0.08); margin: 0 4px; }
.prochart__signal { padding: 2px 8px; font-size: 11px; font-weight: 700; border-radius: 3px; margin-left: auto; }
.prochart__signal--long  { color: var(--buy,  #00d4a3); background: rgba(0,212,163,0.12); }
.prochart__signal--short { color: var(--sell, #f6465d); background: rgba(246,70,93,0.12); }
.prochart__canvas { flex: 1; }
.prochart__stats {
  display: flex; align-items: center; gap: 16px; padding: 4px 12px;
  background: var(--bg-panel, #0d1117);
  border-top: 1px solid var(--border, rgba(255,255,255,0.06));
  font-size: 11px; color: var(--text-muted, #4a5568);
  height: 28px; flex-shrink: 0;
}
.prochart__stats strong { color: var(--text-primary, #e4ebf5); }
.text-buy  { color: var(--buy,  #00d4a3) !important; }
.text-sell { color: var(--sell, #f6465d) !important; }

/* ── Symbol Panel ── */
.symbol-panel { display: flex; flex-direction: column; height: 100%; }
.symbol-panel__tabs { display: flex; border-bottom: 1px solid var(--border, rgba(255,255,255,0.06)); }
.symbol-panel__tabs button { flex: 1; padding: 8px 0; font-size: 12px; font-weight: 500; color: var(--text-secondary, #7d8fa8); background: transparent; border: none; border-bottom: 2px solid transparent; cursor: pointer; }
.symbol-panel__tabs button.active { color: var(--buy, #00d4a3); border-bottom-color: var(--buy, #00d4a3); }
.symbol-panel__search { padding: 8px; border-bottom: 1px solid var(--border, rgba(255,255,255,0.06)); }
.symbol-panel__search input { width: 100%; padding: 5px 8px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 4px; color: var(--text-primary, #e4ebf5); font-size: 12px; outline: none; box-sizing: border-box; }
.symbol-panel__search input:focus { border-color: rgba(255,255,255,0.2); }
.symbol-panel__list { flex: 1; overflow-y: auto; }
.symbol-row { display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 6px 12px; background: transparent; border: none; border-bottom: 1px solid rgba(255,255,255,0.03); cursor: pointer; text-align: left; }
.symbol-row:hover { background: rgba(255,255,255,0.03); }
.symbol-row--active { background: rgba(0,212,163,0.06); }
.symbol-row__name  { font-size: 13px; font-weight: 600; color: var(--text-primary, #e4ebf5); }
.symbol-row__right { display: flex; align-items: center; gap: 8px; }
.symbol-row__price { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-secondary, #7d8fa8); }
.symbol-row__sig--buy  { color: var(--buy,  #00d4a3); font-size: 11px; }
.symbol-row__sig--sell { color: var(--sell, #f6465d); font-size: 11px; }
```

---

## 9. Developer Notes

### Note 1: lightweight-charts v5 Multi-Pane API

Pass `{ pane: 1 }` to `addSeries()` to create a new price pane. Verify with the v5 docs — if `addSeries()` doesn't accept `pane` directly, call `chart.addPane()` first and use the returned pane handle.

### Note 2: Redis Key Discovery

Keys written by the ingestor follow format `v2:coinank:{endpoint_key}:{params_hash}`. Find exact keys with:
```text
redis-cli KEYS "v2:coinank:openInterest_kline:*" | head -5
redis-cli GET <key_from_above>
```
Adjust the pattern-matching in the FastAPI endpoint based on the actual key structure.

### Note 3: CoinAnk Symbol Format

CoinAnk endpoints use `baseCoin` (e.g., `BTC`) not `BTCUSDT`. The endpoint code handles this:
```text
baseCoin = symbol.replace("USDT", "")   # "BTCUSDT" → "BTC"
```

### Note 4: No Direct CoinAnk API Calls from Frontend

The API key is only in the backend. All CoinAnk data must flow through:
```text
ingestor (running) → Redis → FastAPI endpoint → React frontend
```

### Note 5: Liquidation Heatmap (Advanced, Phase E)

The colored vertical bars on the right side of CoinAnk charts require:
1. Reading `v2:coinank:liqMap_getLiqHeatMapSymbol:*` from Redis
2. Parsing price-level → liquidation-amount data
3. Rendering as a custom lightweight-charts `Primitive` plugin

Implement after basic multi-pane chart is working.

### Note 6: SMC Order Blocks (Advanced, Phase E)

The purple/blue shaded rectangles require:
1. Reading `v2:coinank:indicator_smc:*` from Redis
2. Parsing order block levels (price range, type = OB/FVG/Breaker)
3. Rendering as `Primitive` rectangles on the main pane

---

## 10. Implementation Priority

```text
PHASE A — Quick Win (1-2 days)
  1. Create /api/v1/chart/coinank/{symbol}/{timeframe} endpoint
  2. Create /api/v1/chart/symbols endpoint
  3. Apply CSS color tokens to existing chart component

PHASE B — Sub-Panels (3-5 days)
  4. Create ProChart.tsx with multi-pane layout
  5. Wire OI histogram from CoinAnk data
  6. Wire Long/Short histogram
  7. Indicator toggle buttons

PHASE C — Symbol Panel (1-2 days)
  8. Create ProChartSymbolPanel.tsx
  9. Wire /api/v1/chart/symbols with source/freshness-labeled price updates
  10. Symbol stats row below watchlist

PHASE D — Page + Routing (1 day)
  11. Create /chart and /chart/:symbol pages
  12. Add to TopNav SecondaryNav
  13. Link from Trade page

PHASE E — Advanced (5-10 days, optional)
  14. Liquidation heatmap overlay (custom primitive)
  15. SMC order blocks (custom primitive)
  16. BigLiquidation whale markers
  17. Large order markers from bigOrder endpoint
```

---

*Written: 2026-06-13 | Source: CoinAnk proChart screenshot + live_coinank.py ingestor crawl (40+ endpoints)*  
*OHLCV payload confirmed: 100+ symbols × 5 timeframes in chart JSON files*  
*CoinAnk BASE_URL: `https://open-api.coinank.com` — ingestor running, Redis keys populated*
