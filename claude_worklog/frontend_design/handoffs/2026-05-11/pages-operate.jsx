// Operate section pages: Signals, Executions, Positions, Symbols, Paper Trading, Replay

const { SIGNALS, POSITIONS, makeSpark } = window.AIBOT;

function PageHeader({ sub, title, chips, screen }) {
  return (
    <div className="panel bracketed" style={{ marginBottom: 16, padding: "18px 22px" }} data-screen-label={screen}>
      <span className="br-bl" /><span className="br-br" />
      <Eyebrow>// {sub}</Eyebrow>
      <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginTop: 8, flexWrap: "wrap" }}>
        <h1 className="cond" style={{ fontSize: 30 }}>{title}</h1>
        {chips}
      </div>
    </div>
  );
}
window.PageHeader = PageHeader;

function SignalsPage() {
  const SYMS = ["BTC-USDT","ETH-USDT","SOL-USDT","AVAX-USDT","BNB-USDT","MATIC-USDT","ARB-USDT","DOGE-USDT","LINK-USDT","ATOM-USDT"];
  const ROWS = Array.from({ length: 22 }, (_, i) => {
    const r = (s => (s = (s * 9301 + 49297) % 233280) / 233280)(i + 11);
    const sym = SYMS[i % SYMS.length];
    const side = i % 3 === 0 ? "SHORT" : "LONG";
    const conf = (0.51 + ((i * 73) % 41) / 100).toFixed(3);
    const verdict = i % 5 === 4 ? "BLOCK" : "ALLOW";
    const fresh = i % 7 === 5 ? "stale 2.9s" : `fresh ${(0.2 + (i % 7) * 0.1).toFixed(2)}s`;
    const stop = i % 11 === 0 ? "—" : `ATR-${(1.8 + (i % 5) * 0.2).toFixed(1)}`;
    return { id: `01HW9${String.fromCharCode(65 + (i % 26))}${(i*7).toString(36).toUpperCase().slice(0,3)}`,
      t: `13:42:${String(59 - i).padStart(2, "0")}.${String((i * 137) % 999).padStart(3, "0")}`,
      sym, side, conf: +conf, fresh, stop, verdict, pnl: verdict === "BLOCK" ? "—" : (i % 4 === 0 ? `-0.${(10 + i % 30).toString().padStart(2,"0")}%` : `+0.${(11 + i % 60).toString().padStart(2,"0")}%`)
    };
  });
  return (
    <div>
      <PageHeader screen="05 Signals" sub="published signals · v2 lineage chain · model hybrid-v4.2" title="SIGNALS"
        chips={<><Chip kind="ok">STREAM · LIVE</Chip><Chip>{ROWS.length} of 1,847 (24h)</Chip><Chip>1,422 allow · 425 block</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12, marginBottom: 16 }}>
        {[
          { l: "throughput", v: "47 / min", s: 11, t: "var(--ok)" },
          { l: "avg confidence", v: "0.704", s: 22, t: "var(--text)" },
          { l: "allow rate · 24h", v: "76.9%", s: 33, t: "var(--ok)" },
          { l: "feature stale · 1h", v: "11", s: 44, t: "var(--accent)" },
        ].map(k => (
          <div key={k.l} className="panel" style={{ padding: "12px 14px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span className="label-mono">{k.l}</span>
              <svg width="64" height="18" className="spark"><path d={makeSpark(k.s)} stroke={k.t} /></svg>
            </div>
            <div className="kpi-num" style={{ fontSize: 22, marginTop: 6, color: k.t }}>{k.v}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", gap: 10, marginBottom: 12, alignItems: "center", flexWrap: "wrap" }}>
        <input className="input mono" placeholder="filter signal_id, sym, model…" style={{ width: 320 }} />
        <Chip kind="warn">SIDE · ALL</Chip>
        <Chip>VERDICT · ALL</Chip>
        <Chip>SYMBOL · ALL</Chip>
        <Chip>MODEL · hybrid-v4.2-ckpt0291</Chip>
        <Chip>FRESH ≤ 2.5s</Chip>
        <span style={{ flex: 1 }} />
        <button className="btn">EXPORT.NDJSON</button>
        <button className="btn">REPLAY SELECTED</button>
      </div>

      <Panel title="// signal stream · 22 rows" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead>
            <tr><th>time</th><th>signal_id</th><th>symbol</th><th>side</th><th>conf</th><th>features</th><th>stop</th><th>gate</th><th style={{ textAlign: "right" }}>paper pnl</th></tr>
          </thead>
          <tbody>
            {ROWS.map(s => (
              <tr key={s.id} className="row-hover">
                <td className="mono" style={{ color: "var(--text-dim)" }}>{s.t}</td>
                <td className="mono">{s.id}</td>
                <td className="mono">{s.sym}</td>
                <td className="mono" style={{ color: s.side === "LONG" ? "var(--ok)" : "var(--block)", fontWeight: 600 }}>{s.side}</td>
                <td className="mono">
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <div style={{ width: 48, height: 5, background: "var(--bg)", border: "1px solid var(--border)" }}>
                      <div style={{ width: `${s.conf * 100}%`, height: "100%", background: s.conf >= 0.7 ? "var(--ok)" : s.conf >= 0.6 ? "var(--accent)" : "var(--block)" }} />
                    </div>
                    <span style={{ fontSize: 11 }}>{s.conf.toFixed(3)}</span>
                  </div>
                </td>
                <td className="mono" style={{ color: s.fresh.startsWith("stale") ? "var(--accent)" : "var(--text-mid)", fontSize: 11 }}>{s.fresh}</td>
                <td className="mono" style={{ color: s.stop === "—" ? "var(--block)" : "var(--text-mid)", fontSize: 11 }}>{s.stop}</td>
                <td><Chip kind={s.verdict === "ALLOW" ? "ok" : "block"}>{s.verdict}</Chip></td>
                <td className="mono" style={{ textAlign: "right", color: s.pnl.startsWith("+") ? "var(--ok)" : s.pnl.startsWith("-") ? "var(--block)" : "var(--text-dim)" }}>{s.pnl}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

function ExecutionsPage() {
  const ROWS = Array.from({ length: 16 }, (_, i) => {
    const SYMS = ["BTC-USDT","ETH-USDT","SOL-USDT","AVAX-USDT","ARB-USDT","BNB-USDT"];
    const sym = SYMS[i % SYMS.length];
    const side = i % 3 === 0 ? "SELL" : "BUY";
    return {
      id: `EX-${String(284100 - i).padStart(6, "0")}`,
      sig: `01HW9F${(i*3).toString(36).toUpperCase().slice(0,3)}`,
      t: `13:42:${String(58 - i).padStart(2,"0")}.${String((i*131)%999).padStart(3,"0")}`,
      sym, side,
      qty: ((0.04 + i * 0.011) % 2).toFixed(4),
      px: (60000 + i * 12.3).toFixed(2),
      slip: `${(i % 4 === 0 ? "+" : "-")}${(0.01 + (i % 7) * 0.003).toFixed(3)}bp`,
      lat: `${(0.4 + (i * 0.07) % 1.4).toFixed(2)}ms`,
      route: i % 5 === 4 ? "replay-v2" : "paper-direct",
      status: i % 9 === 8 ? "REJECT" : "FILL",
      fee: (0.0008 + (i * 0.0001) % 0.001).toFixed(5),
    };
  });
  return (
    <div>
      <PageHeader screen="06 Executions" sub="execution intents · paper mode · 0 live · audit-pinned" title="EXECUTIONS"
        chips={<><Chip kind="paper">ADAPTER · replay-v2</Chip><Chip kind="ok">FILL RATE 98.2%</Chip><Chip>247 today</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, minmax(0,1fr))", gap: 12, marginBottom: 16 }}>
        {[
          { l: "fills · 24h", v: "1,418", t: "var(--text)" },
          { l: "rejects · 24h", v: "23", t: "var(--block)" },
          { l: "avg slippage", v: "+0.74bp", t: "var(--accent)" },
          { l: "avg latency", v: "0.82ms", t: "var(--ok)" },
          { l: "fee total · 24h", v: "$148.21", t: "var(--text)" },
        ].map(k => (
          <div key={k.l} className="panel" style={{ padding: "12px 14px" }}>
            <span className="label-mono">{k.l}</span>
            <div className="kpi-num" style={{ fontSize: 20, marginTop: 6, color: k.t }}>{k.v}</div>
          </div>
        ))}
      </div>

      <Panel title="// execution intents · latest 16" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>id</th><th>signal</th><th>time</th><th>sym</th><th>side</th><th>qty</th><th>px</th><th>slip</th><th>latency</th><th>route</th><th>fee</th><th>status</th></tr></thead>
          <tbody>
            {ROWS.map(r => (
              <tr key={r.id} className="row-hover">
                <td className="mono">{r.id}</td>
                <td className="mono" style={{ color: "var(--accent)" }}>{r.sig}</td>
                <td className="mono" style={{ color: "var(--text-dim)" }}>{r.t}</td>
                <td className="mono">{r.sym}</td>
                <td className="mono" style={{ color: r.side === "BUY" ? "var(--ok)" : "var(--block)", fontWeight: 600 }}>{r.side}</td>
                <td className="mono">{r.qty}</td>
                <td className="mono">{r.px}</td>
                <td className="mono" style={{ color: r.slip.startsWith("+") ? "var(--accent)" : "var(--ok)" }}>{r.slip}</td>
                <td className="mono">{r.lat}</td>
                <td className="mono" style={{ color: "var(--text-mid)" }}>{r.route}</td>
                <td className="mono">${r.fee}</td>
                <td><Chip kind={r.status === "FILL" ? "ok" : "block"}>{r.status}</Chip></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// reject taxonomy · 24h">
          {[
            { r: "missing_stop_policy", c: 9 },
            { r: "feature_stale", c: 6 },
            { r: "duplicate_order_id", c: 4 },
            { r: "leverage_above_cap", c: 2 },
            { r: "cross_margin_in_live", c: 1 },
            { r: "missing_attribution", c: 1 },
          ].map(x => (
            <div key={x.r} style={{ display: "grid", gridTemplateColumns: "1fr 50px 40px", gap: 10, padding: "5px 0", borderBottom: "1px solid var(--border)", alignItems: "center" }}>
              <span className="mono" style={{ fontSize: 11.5 }}>{x.r}</span>
              <div style={{ height: 6, background: "var(--bg)", border: "1px solid var(--border)" }}>
                <div style={{ width: `${x.c * 10}%`, height: "100%", background: "var(--block)" }} className="hatch-strong" />
              </div>
              <span className="mono" style={{ textAlign: "right", color: "var(--block)" }}>{x.c}</span>
            </div>
          ))}
        </Panel>
        <Panel title="// latency distribution · gate→fill">
          <div style={{ display: "flex", alignItems: "flex-end", height: 120, gap: 4, padding: "12px 0" }}>
            {[12, 24, 38, 56, 71, 89, 64, 41, 27, 15, 8, 4, 2, 1].map((v, i) => (
              <div key={i} style={{ flex: 1, background: i < 6 ? "var(--ok)" : i < 11 ? "var(--accent)" : "var(--block)", height: `${v}%` }} />
            ))}
          </div>
          <div className="mono" style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--text-dim)", marginTop: 4 }}>
            <span>0.2ms</span><span>p50 0.82</span><span>p95 1.41</span><span>p99 2.18</span><span>3.0ms+</span>
          </div>
        </Panel>
      </div>
    </div>
  );
}

function PositionsPage() {
  return (
    <div>
      <PageHeader screen="07 Positions" sub="open positions · paper · cost basis · reconciled" title="POSITIONS"
        chips={<><Chip kind="paper">PAPER</Chip><Chip kind="ok">6 OPEN · 0 STUCK</Chip><Chip>UPNL +$15.22</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12, marginBottom: 16 }}>
        {[
          { l: "gross exposure", v: "$24,818", t: "var(--text)" },
          { l: "net exposure", v: "+$11,402", t: "var(--ok)" },
          { l: "margin used", v: "$3,941", t: "var(--text)" },
          { l: "free margin", v: "$96,170", t: "var(--ok)" },
        ].map(k => (
          <div key={k.l} className="panel" style={{ padding: "12px 14px" }}>
            <span className="label-mono">{k.l}</span>
            <div className="kpi-num" style={{ fontSize: 22, marginTop: 6, color: k.t }}>{k.v}</div>
          </div>
        ))}
      </div>

      <Panel title="// open positions" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>sym</th><th>side</th><th>qty</th><th>entry</th><th>mark</th><th>liq</th><th>upnl</th><th>roe</th><th>fees</th><th>opened</th><th>stop</th><th>tp</th><th></th></tr></thead>
          <tbody>
            {POSITIONS.map((p, i) => (
              <tr key={p.sym} className="row-hover">
                <td className="mono">{p.sym}</td>
                <td className="mono" style={{ color: p.side === "L" ? "var(--ok)" : "var(--block)", fontWeight: 600 }}>{p.side === "L" ? "LONG" : "SHORT"}</td>
                <td className="mono">{p.qty}</td>
                <td className="mono">{p.entry}</td>
                <td className="mono">{p.mark}</td>
                <td className="mono" style={{ color: "var(--text-dim)" }}>{(parseFloat(p.entry.replace(/,/g,"")) * (p.side === "L" ? 0.78 : 1.22)).toFixed(2)}</td>
                <td className="mono" style={{ color: p.upnl.startsWith("+") ? "var(--ok)" : "var(--block)" }}>{p.upnl}</td>
                <td className="mono" style={{ color: p.upnlPct.startsWith("+") ? "var(--ok)" : "var(--block)" }}>{p.upnlPct}</td>
                <td className="mono">${(0.18 + i * 0.04).toFixed(2)}</td>
                <td className="mono" style={{ color: "var(--text-dim)" }}>{p.age}</td>
                <td className="mono" style={{ color: "var(--accent)" }}>ATR-2.{i + 2}</td>
                <td className="mono">0.8R</td>
                <td><button className="btn danger">CLOSE</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.2fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// position lots · cost basis ledger">
          <table className="data">
            <thead><tr><th>sym</th><th>seq</th><th>added</th><th>qty</th><th>px</th><th>fees</th><th>realized</th></tr></thead>
            <tbody>
              {[
                ["BTC-USDT", "L-204", "13:31:11", "0.02", "60,401.10", "0.61", "—"],
                ["BTC-USDT", "L-203", "13:18:02", "0.022", "60,432.80", "0.66", "—"],
                ["ETH-USDT", "S-118", "13:35:42", "0.61", "2,944.20",  "0.45", "+5.12"],
                ["AVAX-USDT", "L-091", "13:38:51", "12.00", "29.81", "0.07", "—"],
                ["SOL-USDT", "L-322", "13:23:11", "1.44", "138.92",  "0.20", "—"],
                ["MATIC-USDT", "L-411", "13:40:21", "210.00", "0.6841", "0.07", "—"],
              ].map(r => (
                <tr key={r[1]} className="row-hover">{r.map((c, i) => <td key={i} className="mono" style={{ color: i === 6 && c.startsWith("+") ? "var(--ok)" : "var(--text)" }}>{c}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel title="// reconciliation · last sync 00:00:42">
          {[
            { k: "paper-ledger vs orchestrator", v: "MATCH", c: "ok" },
            { k: "ledger vs audit-chain", v: "MATCH", c: "ok" },
            { k: "redis pos-cache vs ledger", v: "MATCH", c: "ok" },
            { k: "fills vs lots", v: "MATCH", c: "ok" },
            { k: "fee total drift", v: "0.0001 USD", c: "ok" },
            { k: "subaccount split", v: "n/a · single", c: "" },
          ].map(r => (
            <div key={r.k} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: "1px solid var(--border)", alignItems: "center" }}>
              <span className="mono" style={{ fontSize: 11.5 }}>{r.k}</span>
              <span className="mono" style={{ fontSize: 11, color: r.c === "ok" ? "var(--ok)" : "var(--text-dim)" }}>{r.v}</span>
            </div>
          ))}
        </Panel>
      </div>
    </div>
  );
}

function SymbolsPage() {
  const ROWS = [
    { sym: "BTC-USDT", venue: "binance-spot", uni: "core", regime: "trend-bull", vol: "1,820.4", funding: "−0.0012", oi: "+2.1%", state: "ACTIVE", spark: 11 },
    { sym: "ETH-USDT", venue: "binance-spot", uni: "core", regime: "range",      vol: "1,108.7", funding: "−0.0009", oi: "+0.4%", state: "ACTIVE", spark: 12 },
    { sym: "SOL-USDT", venue: "binance-spot", uni: "core", regime: "trend-bull", vol: "412.0",   funding: "+0.0014", oi: "+5.1%", state: "ACTIVE", spark: 13 },
    { sym: "AVAX-USDT", venue: "binance-spot", uni: "core", regime: "trend-bull", vol: "188.4",  funding: "+0.0008", oi: "+3.1%", state: "ACTIVE", spark: 14 },
    { sym: "BNB-USDT",  venue: "binance-spot", uni: "core", regime: "range",     vol: "98.4",    funding: "−0.0001", oi: "−0.2%", state: "ACTIVE", spark: 15 },
    { sym: "MATIC-USDT",venue: "binance-spot", uni: "core", regime: "trend-bear", vol: "210.7", funding: "−0.0021", oi: "−1.4%", state: "ACTIVE", spark: 16 },
    { sym: "ARB-USDT",  venue: "binance-spot", uni: "core", regime: "trend-bull", vol: "188.4", funding: "+0.0008", oi: "+1.4%", state: "ACTIVE", spark: 17 },
    { sym: "DOGE-USDT", venue: "binance-spot", uni: "watch", regime: "range",    vol: "78.4",   funding: "+0.0001", oi: "+0.1%", state: "WATCH",  spark: 18 },
    { sym: "LINK-USDT", venue: "binance-spot", uni: "watch", regime: "trend-bull", vol: "61.2", funding: "+0.0006", oi: "+2.4%", state: "WATCH",  spark: 19 },
    { sym: "ATOM-USDT", venue: "binance-spot", uni: "watch", regime: "range",    vol: "44.1",   funding: "−0.0002", oi: "−0.1%", state: "PAUSED", spark: 20 },
    { sym: "XRP-USDT",  venue: "okx-spot",     uni: "exclude", regime: "—",      vol: "—",      funding: "—",       oi: "—",    state: "EXCLUDED", spark: 21 },
  ];
  return (
    <div>
      <PageHeader screen="08 Symbols" sub="symbol universe · regime · venue · core / watch / excluded" title="SYMBOLS"
        chips={<><Chip kind="ok">7 ACTIVE</Chip><Chip kind="warn">2 WATCH</Chip><Chip kind="block">1 EXCLUDED</Chip></>} />

      <div style={{ display: "flex", gap: 10, marginBottom: 12, alignItems: "center" }}>
        <input className="input" placeholder="search symbol…" style={{ width: 240 }} />
        <Chip>VENUE · all</Chip><Chip>REGIME · all</Chip><Chip>UNIVERSE · all</Chip>
        <span style={{ flex: 1 }} />
        <button className="btn">+ ADD SYMBOL</button>
      </div>

      <Panel title="// symbol universe" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>symbol</th><th>venue</th><th>universe</th><th>regime</th><th>vol·24h (M)</th><th>funding</th><th>oi Δ</th><th>price · 24h</th><th>state</th><th></th></tr></thead>
          <tbody>
            {ROWS.map(r => (
              <tr key={r.sym} className="row-hover">
                <td className="mono"><strong>{r.sym}</strong></td>
                <td className="mono" style={{ color: "var(--text-mid)" }}>{r.venue}</td>
                <td className="mono"><Chip>{r.uni}</Chip></td>
                <td className="mono" style={{ color: r.regime.includes("bull") ? "var(--ok)" : r.regime.includes("bear") ? "var(--block)" : "var(--text-mid)" }}>{r.regime}</td>
                <td className="mono">{r.vol}</td>
                <td className="mono" style={{ color: r.funding.startsWith("+") ? "var(--ok)" : r.funding.startsWith("−") ? "var(--block)" : "var(--text-dim)" }}>{r.funding}</td>
                <td className="mono" style={{ color: r.oi.startsWith("+") ? "var(--ok)" : r.oi.startsWith("−") ? "var(--block)" : "var(--text-dim)" }}>{r.oi}</td>
                <td><svg width="120" height="22" className="spark"><path d={makeSpark(r.spark, 120, 22, 32)} stroke={r.regime.includes("bull") ? "var(--ok)" : r.regime.includes("bear") ? "var(--block)" : "var(--text-mid)"} /></svg></td>
                <td><Chip kind={r.state === "ACTIVE" ? "ok" : r.state === "EXCLUDED" ? "block" : "warn"}>{r.state}</Chip></td>
                <td><button className="btn">edit</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

function PaperTradingPage() {
  const eq = window.AIBOT.makeEquityPath(900, 200, 128);
  return (
    <div>
      <PageHeader screen="09 Paper Trading" sub="paper loop · isolated · same lineage chain as live · ledger-pinned" title="PAPER TRADING"
        chips={<><Chip kind="paper">PAPER · MODE</Chip><Chip kind="ok">RUNNING · 11:42:08</Chip><Chip>$100,000 → $104,112</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,2fr) minmax(0,1fr)", gap: 16, marginBottom: 16 }}>
        <Panel title="// paper equity · 7-day window" bodyStyle={{ padding: 0 }}>
          <div style={{ padding: 16 }}>
            <svg viewBox={`0 0 900 200`} width="100%" height={200} preserveAspectRatio="none">
              <defs>
                <linearGradient id="pp-grad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--ok)" stopOpacity="0.18" /><stop offset="100%" stopColor="var(--ok)" stopOpacity="0" /></linearGradient>
              </defs>
              {[0.2, 0.4, 0.6, 0.8].map(p => <line key={p} x1="0" x2="900" y1={200 * p} y2={200 * p} stroke="var(--border)" strokeDasharray="2 3" />)}
              <path d={eq.da} fill="url(#pp-grad)" />
              <path d={eq.d} stroke="var(--ok)" fill="none" strokeWidth="1.4" />
            </svg>
          </div>
        </Panel>
        <Panel title="// session summary">
          {[
            { k: "starting equity", v: "$100,000.00", t: "var(--text)" },
            { k: "current equity",  v: "$104,112.42", t: "var(--ok)" },
            { k: "realized pnl",    v: "+$3,098.10",  t: "var(--ok)" },
            { k: "unrealized pnl",  v: "+$1,014.32",  t: "var(--ok)" },
            { k: "trades",          v: "247",         t: "var(--text)" },
            { k: "win rate",        v: "61.4%",       t: "var(--ok)" },
            { k: "avg R",           v: "0.78",        t: "var(--text)" },
            { k: "best trade",      v: "+1.92R",      t: "var(--ok)" },
            { k: "worst trade",     v: "−1.41R",      t: "var(--block)" },
            { k: "max drawdown",    v: "−2.74%",      t: "var(--block)" },
            { k: "sharpe / sortino", v: "1.84 / 2.41", t: "var(--text)" },
            { k: "kill switch",     v: "ARMED",       t: "var(--accent)" },
          ].map(r => (
            <div key={r.k} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
              <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>{r.k}</span>
              <span className="mono" style={{ fontSize: 12, color: r.t }}>{r.v}</span>
            </div>
          ))}
        </Panel>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16 }}>
        <Panel title="// closed trades · last 12" bodyStyle={{ padding: 0 }}>
          <table className="data">
            <thead><tr><th>t</th><th>sym</th><th>side</th><th>R</th><th>pnl</th><th>reason</th></tr></thead>
            <tbody>
              {[
                ["13:21","BTC-USDT","L","+1.21","+$182.30","tp"],
                ["13:18","ETH-USDT","S","+0.82","+$92.10","tp"],
                ["13:14","SOL-USDT","L","-0.41","-$31.40","stop"],
                ["13:09","AVAX-USDT","L","+1.92","+$408.21","tp"],
                ["13:01","DOGE-USDT","S","+0.27","+$11.40","trail"],
                ["12:54","MATIC-USDT","L","+0.64","+$68.10","tp"],
                ["12:48","BNB-USDT","S","-0.21","-$28.81","stop"],
                ["12:42","ARB-USDT","L","+0.81","+$54.10","tp"],
                ["12:38","LINK-USDT","L","+1.04","+$118.40","tp"],
                ["12:31","BTC-USDT","S","-1.41","-$211.18","stop"],
                ["12:22","ETH-USDT","L","+0.42","+$48.10","trail"],
                ["12:14","SOL-USDT","L","+0.78","+$84.41","tp"],
              ].map((r,i) => (
                <tr key={i}><td className="mono" style={{ color: "var(--text-dim)" }}>{r[0]}</td><td className="mono">{r[1]}</td><td className="mono" style={{ color: r[2] === "L" ? "var(--ok)" : "var(--block)" }}>{r[2]}</td><td className="mono" style={{ color: r[3].startsWith("+") ? "var(--ok)" : "var(--block)" }}>{r[3]}</td><td className="mono" style={{ color: r[4].startsWith("+") ? "var(--ok)" : "var(--block)" }}>{r[4]}</td><td className="mono" style={{ color: "var(--text-mid)" }}>{r[5]}</td></tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel title="// equity by strategy">
          {[
            { k: "mass-momentum-v3", v: "+$2,118.20", pct: 64, t: "var(--ok)" },
            { k: "mean-revert-v2", v: "+$612.40", pct: 18, t: "var(--ok)" },
            { k: "breakout-atr-v1", v: "+$382.10", pct: 11, t: "var(--ok)" },
            { k: "funding-skew-v1", v: "+$208.41", pct: 6, t: "var(--ok)" },
            { k: "regime-flip-v0", v: "−$222.91", pct: 7, t: "var(--block)" },
          ].map(s => (
            <div key={s.k} style={{ padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span className="mono" style={{ fontSize: 12 }}>{s.k}</span>
                <span className="mono" style={{ fontSize: 12, color: s.t }}>{s.v}</span>
              </div>
              <div style={{ marginTop: 5, height: 4, background: "var(--bg)", border: "1px solid var(--border)" }}>
                <div style={{ width: `${s.pct}%`, height: "100%", background: s.t }} />
              </div>
            </div>
          ))}
        </Panel>
      </div>
    </div>
  );
}

function ReplayPage() {
  return (
    <div>
      <PageHeader screen="10 Replay" sub="deterministic replay · stored market data · strategy versions · shared lineage" title="REPLAY"
        chips={<><Chip kind="paper">SANDBOX</Chip><Chip kind="ok">DETERMINISM · BYTE-IDENTICAL</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "320px minmax(0,1fr)", gap: 16 }}>
        <Panel title="// new replay run">
          <Eyebrow>strategy</Eyebrow>
          <select className="input" style={{ width: "100%", marginTop: 4 }}><option>mass-momentum-v3 · rev 41</option><option>mean-revert-v2 · rev 22</option><option>breakout-atr-v1 · rev 7</option></select>
          <Eyebrow style={{ marginTop: 14 }}>window</Eyebrow>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginTop: 4 }}>
            <input className="input" defaultValue="2026-04-12" />
            <input className="input" defaultValue="2026-05-09" />
          </div>
          <Eyebrow style={{ marginTop: 14 }}>symbols</Eyebrow>
          <div style={{ marginTop: 4, display: "flex", flexWrap: "wrap", gap: 4 }}>
            {["BTC","ETH","SOL","AVAX","BNB","ARB"].map(s => <Chip kind="warn" key={s}>{s}</Chip>)}
          </div>
          <Eyebrow style={{ marginTop: 14 }}>seed · feature cache</Eyebrow>
          <input className="input" defaultValue="0x4f1c…b09a" style={{ width: "100%", marginTop: 4 }} />
          <div style={{ display: "flex", gap: 6, marginTop: 16 }}>
            <button className="btn primary">START REPLAY</button>
            <button className="btn">SAVE CONFIG</button>
          </div>
        </Panel>

        <Panel title="// replay runs" bodyStyle={{ padding: 0 }}>
          <table className="data">
            <thead><tr><th>id</th><th>strategy</th><th>window</th><th>signals</th><th>fills</th><th>pnl</th><th>sharpe</th><th>dd</th><th>determinism</th><th>state</th></tr></thead>
            <tbody>
              {[
                { id: "RP-0118", s: "mass-momentum-v3 · 41", w: "2026-04-12 → 05-09", sg: 12842, fl: 9712, p: "+$8,401.20", sh: "1.81", dd: "-2.71%", d: "ok", st: "DONE" },
                { id: "RP-0117", s: "mean-revert-v2 · 22",   w: "2026-04-12 → 05-09", sg: 6182,  fl: 4922, p: "+$2,108.10", sh: "1.22", dd: "-1.04%", d: "ok", st: "DONE" },
                { id: "RP-0116", s: "breakout-atr-v1 · 7",   w: "2026-04-01 → 05-01", sg: 3214,  fl: 2418, p: "+$612.40",   sh: "0.94", dd: "-0.81%", d: "ok", st: "DONE" },
                { id: "RP-0115", s: "regime-flip-v0 · 3",    w: "2026-03-01 → 05-01", sg: 2841,  fl: 2104, p: "−$408.10",   sh: "−0.18", dd: "-3.42%", d: "drift", st: "FAIL" },
                { id: "RP-0114", s: "mass-momentum-v3 · 40", w: "2026-03-01 → 05-01", sg: 11420, fl: 8214, p: "+$6,118.40", sh: "1.78", dd: "-2.81%", d: "ok", st: "DONE" },
                { id: "RP-0113", s: "funding-skew-v1 · 11",  w: "2026-04-01 → 05-09", sg: 1812,  fl: 1404, p: "+$1,184.20", sh: "1.14", dd: "-1.04%", d: "ok", st: "DONE" },
                { id: "RP-0112", s: "mean-revert-v2 · 21",   w: "2026-04-12 → 05-09", sg: 6101,  fl: 4810, p: "+$1,841.10", sh: "1.18", dd: "-1.12%", d: "ok", st: "DONE" },
              ].map(r => (
                <tr key={r.id} className="row-hover">
                  <td className="mono">{r.id}</td>
                  <td className="mono">{r.s}</td>
                  <td className="mono" style={{ color: "var(--text-mid)" }}>{r.w}</td>
                  <td className="mono">{r.sg.toLocaleString()}</td>
                  <td className="mono">{r.fl.toLocaleString()}</td>
                  <td className="mono" style={{ color: r.p.startsWith("+") ? "var(--ok)" : "var(--block)" }}>{r.p}</td>
                  <td className="mono">{r.sh}</td>
                  <td className="mono" style={{ color: "var(--block)" }}>{r.dd}</td>
                  <td><Chip kind={r.d === "ok" ? "ok" : "warn"}>{r.d}</Chip></td>
                  <td><Chip kind={r.st === "DONE" ? "ok" : "block"}>{r.st}</Chip></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>
    </div>
  );
}

window.SignalsPage = SignalsPage;
window.ExecutionsPage = ExecutionsPage;
window.PositionsPage = PositionsPage;
window.SymbolsPage = SymbolsPage;
window.PaperTradingPage = PaperTradingPage;
window.ReplayPage = ReplayPage;
===== END FILE: pages-operate.jsx =====

