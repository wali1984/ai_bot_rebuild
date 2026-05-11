// Signal Explainability — single-signal deep dive.

function SignalExplainability() {
  const sig = {
    id: "01HW9F2Z-T7-K3B1-Q-XS21",
    t:   "2026-05-10T13:42:11.804Z",
    sym: "BTC-USDT",
    side: "LONG",
    conf: 0.812,
    calibrated: 0.787,
    model: "hybrid-v4.2",
    ckpt: "0291",
    step: "184,201",
    feature_age_ms: 412,
    stop_class: "ATR-2.4",
    verdict: "ALLOW",
    orch_reason: "regime=trend-bull · book-imbalance=0.61 · funding=−0.0012",
  };
  return (
    <div data-screen-label="08 Signal Explainability">
      <div className="panel bracketed" style={{ marginBottom: 16, padding: "18px 22px" }}>
        <span className="br-bl" /><span className="br-br" />
        <Eyebrow>// signal · explainability · raw evidence pinned</Eyebrow>
        <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginTop: 8, flexWrap: "wrap" }}>
          <h1 className="cond" style={{ fontSize: 30 }}>{sig.sym} · {sig.side}</h1>
          <span className="mono" style={{ fontSize: 12, color: "var(--text-mid)" }}>{sig.id}</span>
          <Chip kind="ok">GATE · ALLOW</Chip>
          <Chip kind="paper">PAPER-FILLED · +0.34%</Chip>
        </div>
        <div className="mono" style={{ marginTop: 10, fontSize: 12, color: "var(--text-dim)" }}>
          published {sig.t} · model {sig.model} · ckpt {sig.ckpt} · step {sig.step}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr) minmax(0,1fr)", gap: 16 }}>
        <Panel title="// model output">
          <KV k="raw output (logits)" v="[ +1.412, −0.703, +0.089 ]" />
          <KV k="softmax"             v="[ 0.812, 0.118, 0.070 ]" />
          <KV k="argmax"              v="LONG" tone="ok" />
          <KV k="confidence (raw)"    v="0.812" />
          <KV k="confidence (calib)"  v="0.787" />
          <KV k="calibration"         v="platt-v3 · brier 0.184" />
          <KV k="model_id"            v="hybrid-v4.2-ckpt0291" mono />
          <KV k="prediction sha"      v="b8d1c1c4d8c0…77c0" mono dim />
        </Panel>

        <Panel title="// feature snapshot">
          {[
            { k: "price.last",       v: "60,418.10",  age: "0.12s", fresh: true },
            { k: "book.imbalance",   v: "+0.61",     age: "0.18s", fresh: true },
            { k: "vol.5m",           v: "1,820.4",   age: "0.30s", fresh: true },
            { k: "funding.next",     v: "−0.0012",   age: "0.40s", fresh: true },
            { k: "regime.label",     v: "trend-bull", age: "0.41s", fresh: true },
            { k: "macd.hist",        v: "+0.0028",   age: "0.42s", fresh: true },
            { k: "atr.14",          v: "182.41",    age: "0.42s", fresh: true },
            { k: "depth.5bp",        v: "12.4 / 11.1", age: "1.41s", fresh: true },
            { k: "social.sent.30m",  v: "0.42",      age: "2.81s", fresh: false },
          ].map(f => (
            <div key={f.k} style={{
              display: "grid", gridTemplateColumns: "1fr auto auto",
              gap: 10, alignItems: "center",
              padding: "6px 0", borderBottom: "1px solid var(--border)",
            }}>
              <span className="mono" style={{ fontSize: 11.5, color: "var(--text)" }}>{f.k}</span>
              <span className="mono" style={{ fontSize: 11.5, color: "var(--text-mid)" }}>{f.v}</span>
              <span className="mono" style={{ fontSize: 10.5, color: f.fresh ? "var(--text-dim)" : "var(--accent)" }}>
                {f.fresh ? "fresh" : "stale"} {f.age}
              </span>
            </div>
          ))}
        </Panel>

        <Panel title="// risk gateway · verdict trace">
          <div style={{ display: "grid", gap: 6 }}>
            {[
              { rule: "attribution.present",   pass: true,  note: "model_id + version present" },
              { rule: "signal_id.present",     pass: true,  note: "uuidv7 valid" },
              { rule: "confidence.calibrated", pass: true,  note: "platt-v3 0.787 ∈ [0,1]" },
              { rule: "feature.freshness",     pass: true,  note: "max age 412ms < 2500ms" },
              { rule: "stop.class.present",    pass: true,  note: "ATR-2.4" },
              { rule: "margin.mode",           pass: true,  note: "ISOLATED · CROSS only in live" },
              { rule: "leverage.cap",          pass: true,  note: "1.5x ≤ 3x (paper cap)" },
              { rule: "dedup.order_id",        pass: true,  note: "0 collisions · 24h window" },
              { rule: "kill.switch.armed",     pass: true,  note: "armed" },
              { rule: "live.enabled",          pass: true,  note: "n/a · paper mode" },
            ].map(r => (
              <div key={r.rule} style={{ display: "grid", gridTemplateColumns: "10px 1fr auto", gap: 10, alignItems: "center", padding: "4px 0" }}>
                <StatusDot status={r.pass ? "ok" : "block"} />
                <div>
                  <div className="mono" style={{ fontSize: 11.5, color: "var(--text)" }}>{r.rule}</div>
                  <div className="mono" style={{ fontSize: 10.5, color: "var(--text-dim)" }}>{r.note}</div>
                </div>
                <span className="mono" style={{ fontSize: 10, color: r.pass ? "var(--ok)" : "var(--block)" }}>{r.pass ? "PASS" : "FAIL"}</span>
              </div>
            ))}
          </div>
          <div className="hatch" style={{ marginTop: 12, padding: "8px 10px", border: "1px solid var(--border)" }}>
            <span className="mono" style={{ fontSize: 11, color: "var(--text)" }}>
              <span style={{ color: "var(--ok)", fontWeight: 600 }}>VERDICT: ALLOW</span>
              <span style={{ color: "var(--text-dim)" }}> · gate latency 0.84ms · gateway rev a7c1b3</span>
            </span>
          </div>
        </Panel>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.4fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// raw evidence pointers · lineage">
          <table className="data">
            <thead><tr><th>artefact</th><th>pointer</th><th>verify</th></tr></thead>
            <tbody>
              {[
                { a: "redis · prediction event", p: "aibotv2:pred:BTC-USDT:184201",            v: "XRANGE aibotv2:pred:BTC-USDT 184201-0 184201-0" },
                { a: "redis · signal event",     p: "aibotv2:sig:01HW9F2Z",                    v: "GET aibotv2:sig:01HW9F2Z" },
                { a: "postgres · audit row",     p: "audit_chain · seq 1,204,481",             v: "SELECT * FROM audit_chain WHERE seq=1204481" },
                { a: "source · risk_gateway.py", p: "v2/backend/risk/gateway.py L142-L188",    v: "git blob 2f1c…aa9 · sha-256 c7…b1" },
                { a: "source · publish.py",      p: "v2/backend/orchestrator/publish.py L91", v: "git blob 8d10…44a · sha-256 31…d2" },
                { a: "checkpoint · 0291",        p: "trainer/ckpt/0291.pt",                    v: "sha-256 7e…fb · size 412 MB" },
                { a: "config · risk.yaml",       p: "v2/config/risk.yaml @ rev 18",            v: "diff rev17→rev18 · 2 lines" },
              ].map(r => (
                <tr key={r.a} className="row-hover">
                  <td className="mono" style={{ color: "var(--text)" }}>{r.a}</td>
                  <td className="mono" style={{ color: "var(--text-mid)" }}>{r.p}</td>
                  <td className="mono" style={{ color: "var(--text-dim)", fontSize: 11 }}>{r.v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title="// orchestrator reasoning">
          <div className="mono" style={{ fontSize: 12, color: "var(--text-mid)", lineHeight: 1.7 }}>
            <span style={{ color: "var(--accent)" }}>regime</span> = <span style={{ color: "var(--text)" }}>trend-bull</span><br/>
            <span style={{ color: "var(--accent)" }}>book.imbalance</span> = <span style={{ color: "var(--text)" }}>+0.61</span><br/>
            <span style={{ color: "var(--accent)" }}>funding.next</span> = <span style={{ color: "var(--text)" }}>−0.0012</span><br/>
            <span style={{ color: "var(--accent)" }}>vol.regime</span> = <span style={{ color: "var(--text)" }}>med · σ-band 2</span><br/>
            <br/>
            <span style={{ color: "var(--text-dim)" }}>→ strategy <span style={{ color: "var(--text)" }}>mass-momentum-v3</span> elected</span><br/>
            <span style={{ color: "var(--text-dim)" }}>→ size <span style={{ color: "var(--text)" }}>0.042 BTC</span> · risk <span style={{ color: "var(--text)" }}>0.18% equity</span></span><br/>
            <span style={{ color: "var(--text-dim)" }}>→ stop <span style={{ color: "var(--text)" }}>ATR-2.4 · 60,000.18</span></span><br/>
            <span style={{ color: "var(--text-dim)" }}>→ target <span style={{ color: "var(--text)" }}>0.78R</span> · trail after 0.5R</span><br/>
          </div>
          <div className="hr" style={{ margin: "14px 0" }} />
          <Eyebrow>missing evidence</Eyebrow>
          <div className="mono" style={{ fontSize: 11, color: "var(--text)", marginTop: 6 }}>
            <span style={{ color: "var(--accent)" }}>·</span> social.sent.30m at 2.81s — within tolerance but flagged for next gate review.
          </div>
        </Panel>
      </div>
    </div>
  );
}

function KV({ k, v, tone, mono, dim }) {
  const c = tone === "ok" ? "var(--ok)" : tone === "block" ? "var(--block)" : dim ? "var(--text-dim)" : "var(--text)";
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 10, padding: "6px 0", borderBottom: "1px solid var(--border)" }}>
      <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>{k}</span>
      <span className={mono ? "mono" : "mono"} style={{ fontSize: 12, color: c, textAlign: "right" }}>{v}</span>
    </div>
  );
}

window.SignalExplainability = SignalExplainability;
===== END FILE: signal-explainability.jsx =====

