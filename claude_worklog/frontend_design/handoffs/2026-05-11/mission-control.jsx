// Mission Control — the operator's home page.

const { SUBSYSTEMS, SIGNALS, POSITIONS, AUDIT, BUILD, TRAINER_PRED, makeEquityPath, makeSpark } = window.AIBOT;

function MissionControl() {
  const tick = useTicker(1400);
  const eq = useMemo(() => makeEquityPath(720, 160, 96), []);

  // simulated live PnL — flips slightly each tick
  const livePnL = useMemo(() => {
    const base = 4112.42;
    const wiggle = ((tick * 137) % 73) / 10 - 3.65;
    return base + wiggle;
  }, [tick]);

  // signal feed shifts top entry
  const feedHead = useMemo(() => {
    const seedIdx = tick % SIGNALS.length;
    return [...SIGNALS.slice(seedIdx), ...SIGNALS.slice(0, seedIdx)];
  }, [tick]);

  return (
    <div data-screen-label="01 Mission Control">
      <MCHero pnl={livePnL} />

      <SubsystemRow />

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.55fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <EquityPanel eq={eq} pnl={livePnL} />
        <RiskGatePanel />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.4fr) minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <SignalStreamPanel signals={feedHead} tick={tick} />
        <PositionsPanel />
        <AuditChainPanel />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.2fr) minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <TrainerMonitorPanel />
        <AgentHealthPanel />
        <BuildValidationPanel />
      </div>
    </div>
  );
}

function MCHero({ pnl }) {
  const clock = useClock();
  return (
    <div className="panel bracketed hatch" style={{ position: "relative", padding: 0, marginBottom: 16 }}>
      <span className="br-bl" /><span className="br-br" />
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.7fr) repeat(4, minmax(0,1fr))", gap: 0 }}>
        <div style={{ padding: "20px 22px 20px", borderRight: "1px solid var(--border)" }}>
          <Eyebrow>// AI BOT V2 · control plane · session ░░░░-0291-z</Eyebrow>
          <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginTop: 8 }}>
            <h1 className="cond" style={{ fontSize: 36, lineHeight: 1, letterSpacing: "-0.01em" }}>
              MISSION CONTROL
            </h1>
            <Chip kind="block">LIVE TRADING · BLOCKED</Chip>
          </div>
          <div className="mono" style={{ marginTop: 12, color: "var(--text-mid)", fontSize: 12 }}>
            paper mode · replay adapter v2 · operator <span style={{ color: "var(--text)" }}>wali1984</span> · {fmtDate(clock)} {fmtClock(clock)}
          </div>
        </div>
        <HeroStat label="paper equity"   value="$104,112.42"     sub="+4.11% session"    tone="ok" />
        <HeroStat label="open positions" value="6"                sub="3L · 3S · 0 stuck" tone="text" />
        <HeroStat label="signals · 24h"  value="1,847"            sub="1,422 allow · 425 block" tone="text" />
        <HeroStat label="kill switch"    value="ARMED"            sub="trip-latency 0.2s" tone="warn" border={false} />
      </div>
    </div>
  );
}

function HeroStat({ label, value, sub, tone = "text", border = true }) {
  const color = tone === "ok" ? "var(--ok)" : tone === "warn" ? "var(--accent)" : tone === "block" ? "var(--block)" : "var(--text)";
  return (
    <div style={{ padding: "20px 18px", borderRight: border ? "1px solid var(--border)" : 0, background: "var(--panel)" }}>
      <div className="label-mono">{label}</div>
      <div className="kpi-num" style={{ fontSize: 26, marginTop: 6, color, lineHeight: 1 }}>{value}</div>
      <div className="mono" style={{ marginTop: 6, fontSize: 11, color: "var(--text-dim)" }}>{sub}</div>
    </div>
  );
}

function SubsystemRow() {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(6, minmax(0,1fr))", gap: 12 }}>
      {SUBSYSTEMS.map(s => (
        <div key={s.id} className="panel" style={{ padding: "11px 13px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div className="label-mono" style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <StatusDot status={s.status} pulse={s.status === "ok"} />
              {s.label}
            </div>
            <span className="mono" style={{ fontSize: 10, color: "var(--text-dim)" }}>{s.last}</span>
          </div>
          <div className="kpi-num" style={{
            fontSize: 14, marginTop: 8,
            color: s.status === "block" ? "var(--block)" : s.status === "paper" ? "var(--paper)" : s.status === "warn" ? "var(--accent)" : "var(--text)",
          }}>
            {s.metric}
          </div>
          <div className="mono" style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 4 }}>{s.detail}</div>
        </div>
      ))}
    </div>
  );
}

function EquityPanel({ eq, pnl }) {
  const W = 720, H = 180;
  return (
    <Panel
      title="// paper equity · session"
      right={
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span className="label-mono" style={{ color: "var(--text-dim)" }}>since 09:30 UTC</span>
          <Chip>1H</Chip>
          <Chip kind="warn">SESSION</Chip>
          <Chip>24H</Chip>
          <Chip>7D</Chip>
        </div>
      }
      bodyStyle={{ padding: 0 }}
    >
      <div style={{ display: "grid", gridTemplateColumns: "240px 1fr" }}>
        <div style={{ padding: 18, borderRight: "1px solid var(--border)" }}>
          <Eyebrow>equity (paper)</Eyebrow>
          <div className="kpi-num" style={{ fontSize: 32, marginTop: 4, lineHeight: 1 }}>$104,112<span style={{ color: "var(--text-mid)", fontSize: 22 }}>.42</span></div>
          <div className="mono" style={{ marginTop: 4, fontSize: 11, color: "var(--ok)" }}>+$4,112.42 · +4.11%</div>

          <div style={{ marginTop: 22 }}>
            <Eyebrow>realized · session</Eyebrow>
            <div className="kpi-num" style={{ fontSize: 18, marginTop: 2, color: "var(--ok)" }}>+$3,098.10</div>
          </div>
          <div style={{ marginTop: 14 }}>
            <Eyebrow>unrealized</Eyebrow>
            <div className="kpi-num" style={{ fontSize: 18, marginTop: 2, color: "var(--ok)" }}>+$1,014.32</div>
          </div>
          <div style={{ marginTop: 14 }}>
            <Eyebrow>max drawdown · 7d</Eyebrow>
            <div className="kpi-num" style={{ fontSize: 18, marginTop: 2, color: "var(--block)" }}>−2.74%</div>
          </div>
        </div>
        <div style={{ position: "relative", padding: "14px 18px 18px" }}>
          <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" style={{ display: "block" }}>
            <defs>
              <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"  stopColor="var(--ok)" stopOpacity="0.18" />
                <stop offset="100%" stopColor="var(--ok)" stopOpacity="0" />
              </linearGradient>
              <pattern id="eqGrid" width="60" height="40" patternUnits="userSpaceOnUse">
                <path d="M 60 0 L 0 0 0 40" fill="none" stroke="var(--grid-line)" strokeWidth="1" />
              </pattern>
            </defs>
            <rect width={W} height={H} fill="url(#eqGrid)" />
            {[0.25, 0.5, 0.75].map(p => (
              <line key={p} x1="0" x2={W} y1={H * p} y2={H * p} stroke="var(--border)" strokeDasharray="2 3" opacity="0.6" />
            ))}
            <path d={eq.da} fill="url(#eqGrad)" />
            <path d={eq.d}  stroke="var(--ok)" strokeWidth="1.4" fill="none" />
            {/* live cursor */}
            <line x1={W - 0.5} x2={W - 0.5} y1="0" y2={H} stroke="var(--accent)" strokeDasharray="2 2" opacity="0.6" />
            <circle cx={W - 2} cy={(H * 0.18).toFixed(2)} r="3" fill="var(--accent)" />
          </svg>
          <div style={{ position: "absolute", top: 16, right: 22, textAlign: "right" }} className="mono">
            <div style={{ fontSize: 10, color: "var(--text-dim)" }}>SHARPE / SORTINO</div>
            <div className="kpi-num" style={{ fontSize: 14, color: "var(--text)" }}>1.84 / 2.41</div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginTop: 8 }}>
            <MiniStat label="trades" value="247" />
            <MiniStat label="win-rate" value="61.4%" tone="ok" />
            <MiniStat label="avg R" value="0.78" />
            <MiniStat label="best/worst" value="+1.92 / −1.41" />
          </div>
        </div>
      </div>
    </Panel>
  );
}

function MiniStat({ label, value, tone }) {
  const c = tone === "ok" ? "var(--ok)" : tone === "block" ? "var(--block)" : "var(--text)";
  return (
    <div>
      <div className="label-mono">{label}</div>
      <div className="kpi-num" style={{ fontSize: 14, color: c }}>{value}</div>
    </div>
  );
}

function RiskGatePanel() {
  const allow = 1422, block = 425, stale = 11;
  const total = allow + block + stale;
  const ap = (allow / total) * 100, bp = (block / total) * 100, sp = (stale / total) * 100;
  return (
    <Panel title="// risk gateway · 24h"
      right={<Chip kind="warn">12 RULES ARMED</Chip>}
    >
      <div style={{ display: "flex", height: 10, border: "1px solid var(--border)", overflow: "hidden" }}>
        <div style={{ width: `${ap}%`, background: "var(--ok)" }} />
        <div style={{ width: `${bp}%`, background: "var(--block)" }} className="hatch-strong" />
        <div style={{ width: `${sp}%`, background: "var(--warn)" }} />
      </div>
      <div className="mono" style={{ display: "flex", justifyContent: "space-between", marginTop: 6, fontSize: 11, color: "var(--text-mid)" }}>
        <span><StatusDot status="ok" /> allow <span style={{ color: "var(--text)" }}>{allow}</span></span>
        <span><StatusDot status="block" /> block <span style={{ color: "var(--text)" }}>{block}</span></span>
        <span><StatusDot status="warn" /> stale <span style={{ color: "var(--text)" }}>{stale}</span></span>
      </div>

      <div style={{ marginTop: 16 }}>
        <Eyebrow>top blocks · last 24h</Eyebrow>
        <div style={{ marginTop: 8 }}>
          {[
            { rule: "stale-risk-add", c: 142, sym: "feature tick > 2.5s" },
            { rule: "missing-stop",   c: 96,  sym: "no stop class" },
            { rule: "leverage-cap",   c: 71,  sym: "leverage > 3x" },
            { rule: "duplicate-order-id", c: 64, sym: "dedup window 24h" },
            { rule: "missing-confidence", c: 38, sym: "calibration null" },
            { rule: "cross-margin",   c: 14,  sym: "CROSS in paper-live" },
          ].map(r => (
            <div key={r.rule} style={{ display: "grid", gridTemplateColumns: "150px 1fr 40px", gap: 10, alignItems: "center", padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
              <span className="mono" style={{ fontSize: 11, color: "var(--text)" }}>{r.rule}</span>
              <span className="mono" style={{ fontSize: 10.5, color: "var(--text-dim)" }}>{r.sym}</span>
              <span className="kpi-num" style={{ fontSize: 12, textAlign: "right", color: "var(--block)" }}>{r.c}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="hatch" style={{ marginTop: 14, padding: "10px 12px", border: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 10 }}>
        <StatusDot status="block" pulse />
        <span className="mono" style={{ fontSize: 11 }}>
          <span style={{ color: "var(--block)", fontWeight: 600 }}>LIVE ENABLE</span>
          <span style={{ color: "var(--text-mid)" }}> · requires </span>
          <span style={{ color: "var(--text)" }}>2-operator approval · 9/14 readiness items pending</span>
        </span>
      </div>
    </Panel>
  );
}

function SignalStreamPanel({ signals, tick }) {
  return (
    <Panel title="// signal stream"
      right={
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <StatusDot status="ok" pulse />
          <span className="label-mono">{47 + (tick % 4)} / min</span>
          <span style={{ color: "var(--text-faint)" }}>·</span>
          <span className="label-mono">model hybrid-v4.2-ckpt0291</span>
        </div>
      }
      bodyStyle={{ padding: 0 }}
    >
      <table className="data">
        <thead>
          <tr>
            <th style={{ width: 70 }}>time</th>
            <th style={{ width: 80 }}>signal_id</th>
            <th>symbol</th>
            <th>side</th>
            <th>conf</th>
            <th>features</th>
            <th>stop</th>
            <th>gate</th>
            <th style={{ textAlign: "right" }}>pnl</th>
          </tr>
        </thead>
        <tbody>
          {signals.slice(0, 8).map((s, i) => (
            <tr key={s.id + i} className="row-hover" style={{ background: i === 0 ? "color-mix(in oklch, var(--accent) 6%, transparent)" : "transparent" }}>
              <td className="mono" style={{ color: "var(--text-dim)", fontSize: 11 }}>{s.t.slice(0, 8)}</td>
              <td className="mono" style={{ color: "var(--text)" }}>{s.id}</td>
              <td className="mono" style={{ color: "var(--text)" }}>{s.sym}</td>
              <td className="mono" style={{ color: s.side === "LONG" ? "var(--ok)" : "var(--block)", fontWeight: 600 }}>{s.side}</td>
              <td><ConfBar v={s.conf} /></td>
              <td className="mono" style={{ color: s.feat.startsWith("stale") ? "var(--accent)" : "var(--text-mid)", fontSize: 11 }}>{s.feat}</td>
              <td className="mono" style={{ color: s.stop === "—" ? "var(--block)" : "var(--text-mid)", fontSize: 11 }}>{s.stop}</td>
              <td>
                <Chip kind={s.verdict === "ALLOW" ? "ok" : "block"} style={{ padding: "1px 6px" }}>
                  {s.verdict}
                </Chip>
              </td>
              <td className="mono" style={{ textAlign: "right", color: s.pnl.startsWith("+") ? "var(--ok)" : s.pnl.startsWith("-") ? "var(--block)" : "var(--text-dim)" }}>{s.pnl}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function ConfBar({ v }) {
  const pct = Math.round(v * 100);
  const tone = v >= 0.70 ? "var(--ok)" : v >= 0.60 ? "var(--accent)" : "var(--block)";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 80 }}>
      <div style={{ width: 50, height: 6, background: "var(--bg)", border: "1px solid var(--border)" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: tone }} />
      </div>
      <span className="mono" style={{ fontSize: 11, color: "var(--text)", width: 28 }}>{v.toFixed(2)}</span>
    </div>
  );
}

function PositionsPanel() {
  return (
    <Panel title="// positions (paper)"
      right={<span className="label-mono">6 open · 0 stuck</span>}
      bodyStyle={{ padding: 0 }}
    >
      <table className="data">
        <thead>
          <tr>
            <th>sym</th><th>s</th><th>qty</th><th>mark</th><th style={{ textAlign: "right" }}>upnl</th>
          </tr>
        </thead>
        <tbody>
          {POSITIONS.map(p => (
            <tr key={p.sym} className="row-hover">
              <td className="mono" style={{ color: "var(--text)" }}>{p.sym}</td>
              <td className="mono" style={{ color: p.side === "L" ? "var(--ok)" : "var(--block)", fontWeight: 600 }}>{p.side}</td>
              <td className="mono" style={{ color: "var(--text-mid)" }}>{p.qty}</td>
              <td className="mono" style={{ color: "var(--text-mid)" }}>{p.mark}</td>
              <td className="mono" style={{ textAlign: "right", color: p.upnl.startsWith("+") ? "var(--ok)" : "var(--block)" }}>
                {p.upnl}<span style={{ color: "var(--text-dim)", marginLeft: 6 }}>{p.upnlPct}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function AuditChainPanel() {
  return (
    <Panel title="// audit ledger · tail"
      right={
        <span className="label-mono">
          <StatusDot status="ok" /> 1,204,481 links · 0 breaks
        </span>
      }
      bodyStyle={{ padding: 0 }}
    >
      <div>
        {AUDIT.slice(0, 7).map((a, i) => (
          <div key={a.seq} style={{
            display: "grid",
            gridTemplateColumns: "10px 60px 1fr 70px",
            gap: 8,
            alignItems: "center",
            padding: "7px 12px",
            borderBottom: i === AUDIT.length - 1 ? 0 : "1px solid var(--border)",
          }}>
            <StatusDot status={a.verdict === "ok" ? "ok" : "block"} />
            <span className="mono" style={{ fontSize: 10, color: "var(--text-dim)" }}>{a.t.slice(0,8)}</span>
            <div style={{ minWidth: 0 }}>
              <div className="mono" style={{ fontSize: 11, color: "var(--text)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                <span style={{ color: "var(--accent)" }}>{a.actor}</span>
                <span style={{ color: "var(--text-dim)" }}> · </span>
                {a.action}
              </div>
              <div className="mono" style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {a.target}
              </div>
            </div>
            <span className="mono" style={{ fontSize: 10, color: "var(--text-faint)", textAlign: "right" }}>{a.curr}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function TrainerMonitorPanel() {
  return (
    <Panel
      title="// trainer · prediction monitor"
      right={
        <span className="label-mono">
          <StatusDot status="ok" pulse /> hybrid-v4.2 · ckpt 0291 · step 184,201
        </span>
      }
      bodyStyle={{ padding: 0 }}
    >
      <table className="data">
        <thead>
          <tr>
            <th>symbol</th><th>acc</th><th>mae</th><th>brier</th><th>drift</th><th style={{ textAlign: "right" }}>last</th>
          </tr>
        </thead>
        <tbody>
          {TRAINER_PRED.map(t => (
            <tr key={t.sym} className="row-hover">
              <td className="mono">{t.sym}</td>
              <td className="mono"><BarCell v={t.acc} max={0.7} tone={t.acc >= 0.59 ? "var(--ok)" : "var(--accent)"} /></td>
              <td className="mono">{t.mae.toFixed(4)}</td>
              <td className="mono">{t.brier.toFixed(3)}</td>
              <td className="mono" style={{ color: t.drift > 0.15 ? "var(--accent)" : "var(--text-mid)" }}>
                {t.drift.toFixed(2)}
              </td>
              <td className="mono" style={{ textAlign: "right", color: t.last.startsWith("3") ? "var(--accent)" : "var(--text-dim)" }}>{t.last}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

function BarCell({ v, max = 1, tone = "var(--text)" }) {
  const pct = Math.min(100, (v / max) * 100);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 80 }}>
      <div style={{ width: 44, height: 4, background: "var(--bg)", border: "1px solid var(--border)" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: tone }} />
      </div>
      <span className="mono" style={{ fontSize: 11, color: "var(--text)", width: 32 }}>{v.toFixed(3)}</span>
    </div>
  );
}

function AgentHealthPanel() {
  const agents = [
    { name: "Claude (max 5x)",  status: "ok",   detail: "/usage 38% · session bounded",       spark: 11 },
    { name: "Ollama (local)",    status: "ok",   detail: "qwen2.5:14b · 23 packets queued",    spark: 22 },
    { name: "Codex review",      status: "warn", detail: "milestone C queued · 3 gates open",  spark: 33 },
  ];
  return (
    <Panel title="// ai supervision · health" right={<Chip>3 layers</Chip>}>
      <div style={{ display: "grid", gap: 10 }}>
        {agents.map(a => (
          <div key={a.name} style={{ padding: "10px 12px", border: "1px solid var(--border)", background: "var(--panel-2)" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <StatusDot status={a.status} pulse={a.status === "ok"} />
                <span className="mono" style={{ fontSize: 12, color: "var(--text)" }}>{a.name}</span>
              </span>
              <svg width="64" height="18" className="spark"><path d={makeSpark(a.spark)} stroke={a.status === "warn" ? "var(--accent)" : "var(--ok)"} /></svg>
            </div>
            <div className="mono" style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 6 }}>{a.detail}</div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 12, padding: "8px 10px", border: "1px dashed var(--border-strong)", display: "flex", justifyContent: "space-between" }}>
        <span className="label-mono">evidence integrity</span>
        <span className="mono" style={{ fontSize: 11 }}>
          <span style={{ color: "var(--ok)" }}>raw-verified 412</span>
          <span style={{ color: "var(--text-dim)" }}> · </span>
          <span style={{ color: "var(--accent)" }}>unverified 14</span>
        </span>
      </div>
    </Panel>
  );
}

function BuildValidationPanel() {
  return (
    <Panel title="// build · validation status"
      right={<Chip kind="warn">4 warn · 0 fail</Chip>}
    >
      <div>
        {BUILD.map(b => (
          <div key={b.id} style={{
            display: "grid",
            gridTemplateColumns: "44px 1fr 56px",
            gap: 10,
            alignItems: "center",
            padding: "7px 0",
            borderBottom: "1px solid var(--border)",
          }}>
            <span className="mono" style={{ fontSize: 10, color: "var(--text-dim)" }}>{b.id}</span>
            <div style={{ minWidth: 0 }}>
              <div className="mono" style={{ fontSize: 11.5, color: "var(--text)" }}>{b.label}</div>
              <div className="mono" style={{ fontSize: 10.5, color: "var(--text-dim)", marginTop: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{b.detail}</div>
            </div>
            <span style={{ textAlign: "right" }}>
              <Chip kind={b.status === "PASS" ? "ok" : b.status === "WARN" ? "warn" : "block"}>{b.status}</Chip>
            </span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

window.MissionControl = MissionControl;
===== END FILE: mission-control.jsx =====

