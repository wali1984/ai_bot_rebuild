// System: System Health, Build/Validation, Mobile Readiness

function SystemHealthPage() {
  const SVC = [
    { name: "trainer",       host: "trainer-01.lan",   v: "1.18.0", up: "11d 14h", cpu: 41, mem: 62, disk: 18, net: "1.2 MB/s", st: "ok" },
    { name: "orchestrator",  host: "orch-01.lan",      v: "2.04.0", up: "11d 14h", cpu: 18, mem: 28, disk: 4,  net: "0.8 MB/s", st: "ok" },
    { name: "risk-gateway",  host: "risk-01.lan",      v: "3.02.1", up: "11d 14h", cpu:  8, mem: 12, disk: 2,  net: "0.4 MB/s", st: "ok" },
    { name: "execution",     host: "exec-01.lan",      v: "1.07.0", up: "11d 14h", cpu: 12, mem: 18, disk: 6,  net: "0.3 MB/s", st: "ok" },
    { name: "audit",          host: "audit-01.lan",     v: "1.21.0", up: "21d 02h", cpu:  6, mem: 14, disk: 38, net: "0.1 MB/s", st: "ok" },
    { name: "redis",         host: "redis-01.lan",     v: "7.2.4",  up: "21d 02h", cpu: 11, mem: 22, disk: 12, net: "1.6 MB/s", st: "ok" },
    { name: "postgres",      host: "pg-01.lan",        v: "16.2",   up: "21d 02h", cpu:  8, mem: 41, disk: 64, net: "0.4 MB/s", st: "ok" },
    { name: "ollama",        host: "ai-gpu-01.lan",    v: "0.1.41", up: "11d 14h", cpu: 14, mem: 38, disk: 22, net: "0.1 MB/s", st: "ok" },
    { name: "monitor",       host: "mon-01.lan",       v: "0.8.2",  up: "11d 14h", cpu:  4, mem:  8, disk: 4,  net: "0.2 MB/s", st: "ok" },
  ];
  return (
    <div>
      <PageHeader screen="25 System Health" sub="services · hosts · resources · heartbeat 1s" title="SYSTEM HEALTH"
        chips={<><Chip kind="ok">9 / 9 SERVICES</Chip><Chip>uptime 11d 14h</Chip><Chip>0 incidents · 7d</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12, marginBottom: 16 }}>
        {[
          { l: "cpu (cluster avg)",   v: "13.8%", t: "var(--ok)" },
          { l: "mem (cluster avg)",   v: "27.1%", t: "var(--ok)" },
          { l: "disk (worst)",         v: "64%",   t: "var(--accent)" },
          { l: "net (cluster)",        v: "5.1 MB/s", t: "var(--text)" },
        ].map(k => (
          <div key={k.l} className="panel" style={{ padding: "12px 14px" }}>
            <span className="label-mono">{k.l}</span>
            <div className="kpi-num" style={{ fontSize: 22, marginTop: 6, color: k.t }}>{k.v}</div>
          </div>
        ))}
      </div>

      <Panel title="// services" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>service</th><th>host</th><th>v</th><th>uptime</th><th>cpu</th><th>mem</th><th>disk</th><th>net</th><th>state</th></tr></thead>
          <tbody>
            {SVC.map(s => (
              <tr key={s.name} className="row-hover">
                <td className="mono"><strong>{s.name}</strong></td>
                <td className="mono" style={{ color: "var(--text-mid)" }}>{s.host}</td>
                <td className="mono">{s.v}</td>
                <td className="mono" style={{ color: "var(--text-dim)" }}>{s.up}</td>
                {[s.cpu, s.mem, s.disk].map((p, i) => (
                  <td key={i} style={{ minWidth: 80 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <div style={{ flex: 1, height: 4, background: "var(--bg)", border: "1px solid var(--border)" }}>
                        <div style={{ width: `${p}%`, height: "100%", background: p > 70 ? "var(--block)" : p > 50 ? "var(--accent)" : "var(--ok)" }} />
                      </div>
                      <span className="mono" style={{ fontSize: 10, color: "var(--text-dim)", minWidth: 24, textAlign: "right" }}>{p}%</span>
                    </div>
                  </td>
                ))}
                <td className="mono" style={{ fontSize: 11 }}>{s.net}</td>
                <td><Chip kind="ok">{s.st.toUpperCase()}</Chip></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// recent incidents · 30d">
          {[
            ["2026-04-22 03:12", "redis · transient eviction spike", "5min", "resolved"],
            ["2026-04-18 11:48", "trainer · ckpt save slow",         "11min", "resolved"],
            ["2026-04-11 22:01", "postgres · replica lag 41ms",      "8min",  "resolved"],
          ].map((r, i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "150px 1fr 60px 80px", gap: 10, padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
              {r.map((c, j) => <span key={j} className="mono" style={{ fontSize: 11, color: j === 0 ? "var(--text-dim)" : j === 3 ? "var(--ok)" : "var(--text)" }}>{c}</span>)}
            </div>
          ))}
        </Panel>
        <Panel title="// dependencies · external">
          {[
            ["binance-spot · market data", "ok", "ws 14ms"],
            ["bybit · market data",         "ok", "ws 18ms"],
            ["okx · market data",           "ok", "ws 21ms"],
            ["claude · api",                "ok", "rest p99 2.8s"],
            ["coingecko · ref data",        "ok", "rest 412ms"],
            ["binance · live trading",      "blocked", "policy"],
          ].map((r, i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 80px 80px", gap: 10, padding: "5px 0", borderBottom: "1px solid var(--border)", alignItems: "center" }}>
              <span className="mono" style={{ fontSize: 11.5 }}>{r[0]}</span>
              <Chip kind={r[1] === "ok" ? "ok" : "block"}>{r[1].toUpperCase()}</Chip>
              <span className="mono" style={{ fontSize: 10, color: "var(--text-dim)", textAlign: "right" }}>{r[2]}</span>
            </div>
          ))}
        </Panel>
      </div>
    </div>
  );
}

function BuildValidationPage() {
  const { BUILD } = window.AIBOT;
  return (
    <div>
      <PageHeader screen="26 Build Validation" sub="scaffold validation · milestone reviews · evidence chain" title="BUILD / VALIDATION"
        chips={<><Chip kind="ok">5 PASS</Chip><Chip kind="warn">3 WARN</Chip><Chip>milestone C</Chip></>} />

      <div className="panel hatch" style={{ padding: 16, marginBottom: 16, borderLeft: "3px solid var(--accent)" }}>
        <Eyebrow style={{ color: "var(--accent)" }}>// roadmap · priority order</Eyebrow>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 14, marginTop: 12 }}>
          {[
            { p: "P0", n: "1", k: "live adapter implementation",     w: "execution",  s: "in-progress" },
            { p: "P0", n: "2", k: "contract tests for live adapter", w: "execution",  s: "planned" },
            { p: "P0", n: "3", k: "operator dual-control sign-off",  w: "risk + ops", s: "planned" },
            { p: "P1", n: "4", k: "exchange connector matrix",       w: "execution",  s: "stub" },
            { p: "P1", n: "5", k: "feature freshness < 2s",          w: "trainer",    s: "in-progress" },
            { p: "P1", n: "6", k: "audit witness external service",  w: "audit",      s: "stub" },
            { p: "P2", n: "7", k: "ops runbook to 100%",             w: "ops",        s: "in-progress" },
            { p: "P2", n: "8", k: "mobile parity for kill switch",    w: "ops",        s: "in-progress" },
          ].map(it => (
            <div key={it.n} className="panel" style={{ padding: 12, background: "var(--bg)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <Chip kind={it.p === "P0" ? "block" : it.p === "P1" ? "warn" : null}>{it.p}</Chip>
                <span className="mono" style={{ fontSize: 10, color: "var(--text-dim)" }}>#{it.n}</span>
              </div>
              <div className="cond" style={{ fontSize: 14, marginTop: 8 }}>{it.k}</div>
              <div className="mono" style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 4 }}>{it.w}</div>
              <Chip style={{ marginTop: 8 }} kind={it.s === "in-progress" ? "warn" : null}>{it.s}</Chip>
            </div>
          ))}
        </div>
      </div>

      <Panel title="// validation gates · last cron 14:02" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>id</th><th>gate</th><th>state</th><th>detail</th><th>evidence</th></tr></thead>
          <tbody>
            {BUILD.map(b => (
              <tr key={b.id} className="row-hover">
                <td className="mono">{b.id}</td>
                <td className="mono">{b.label}</td>
                <td><Chip kind={b.status === "PASS" ? "ok" : b.status === "WARN" ? "warn" : "block"}>{b.status}</Chip></td>
                <td className="mono" style={{ fontSize: 11.5, color: "var(--text-mid)" }}>{b.detail}</td>
                <td><button className="btn">open</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// milestone history">
          {[
            ["M-A · scaffold + atlas",         "2026-04-12", "passed"],
            ["M-B · trainer + orchestrator",    "2026-04-22", "passed"],
            ["M-C · risk + paper + audit",      "2026-05-09", "in-review"],
            ["M-D · live adapter + readiness",  "—",          "planned"],
            ["M-E · live trading enabled",     "—",          "planned"],
          ].map((r, i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "1fr 100px 100px", gap: 10, padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
              <span className="mono" style={{ fontSize: 12 }}>{r[0]}</span>
              <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>{r[1]}</span>
              <Chip kind={r[2] === "passed" ? "ok" : r[2] === "in-review" ? "warn" : null}>{r[2]}</Chip>
            </div>
          ))}
        </Panel>
        <Panel title="// cron schedule">
          <KVTable rows={[
            ["scaffold.validate", "*/5min"],
            ["redis.namespace.audit", "*/15min"],
            ["audit.chain.verify", "*/1h"],
            ["atlas.coverage.recompute", "*/1h"],
            ["readiness.checklist.refresh", "*/15min"],
            ["claude.shift.narrate", "*/4h"],
            ["codex.queue.scan", "*/10min"],
          ]} />
        </Panel>
      </div>
    </div>
  );
}

function MobileReadinessPage() {
  return (
    <div>
      <PageHeader screen="27 Mobile Readiness" sub="iOS companion · operator surface · paper parity" title="MOBILE / IPHONE READINESS"
        chips={<><Chip kind="warn">BETA</Chip><Chip kind="paper">PAPER · KILL SWITCH OK</Chip><Chip>build 0.4.1-rc2</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "320px minmax(0,1fr)", gap: 16, alignItems: "start" }}>
        <div style={{ background: "var(--bg)", padding: 18, border: "1px solid var(--border)", borderRadius: 36, position: "relative" }}>
          <div style={{ width: 110, height: 18, background: "var(--surface-3)", borderRadius: 10, margin: "0 auto 12px" }} />
          <div style={{ background: "var(--surface)", border: "1px solid var(--border)", padding: "14px 12px", borderRadius: 24 }}>
            <div className="mono" style={{ fontSize: 9, color: "var(--text-dim)" }}>14:02 UTC · op wali1984</div>
            <div className="cond" style={{ fontSize: 17, marginTop: 6 }}>AI BOT · CONTROL</div>
            <div className="hr" style={{ margin: "10px 0" }} />
            <Chip kind="block" style={{ width: "100%", textAlign: "center", padding: "8px 0" }}>LIVE · BLOCKED</Chip>
            <Chip kind="paper" style={{ width: "100%", textAlign: "center", padding: "8px 0", marginTop: 6 }}>PAPER · ACTIVE</Chip>
            <div className="hr" style={{ margin: "10px 0" }} />
            {[
              ["equity", "$104,112"],
              ["upnl", "+$15.22"],
              ["open pos", "6"],
              ["throughput", "9.4 /s"],
              ["gate latency", "0.84ms"],
            ].map(r => (
              <div key={r[0]} style={{ display: "flex", justifyContent: "space-between", padding: "4px 0" }}>
                <span className="mono" style={{ fontSize: 10.5, color: "var(--text-dim)" }}>{r[0]}</span>
                <span className="mono" style={{ fontSize: 11, color: "var(--text)" }}>{r[1]}</span>
              </div>
            ))}
            <div className="hr" style={{ margin: "10px 0" }} />
            <button className="btn danger" style={{ width: "100%", padding: "10px 0" }}>KILL SWITCH</button>
            <div className="mono" style={{ fontSize: 9, color: "var(--text-dim)", textAlign: "center", marginTop: 6 }}>requires biometric + pin</div>
          </div>
        </div>

        <div style={{ display: "grid", gap: 16 }}>
          <Panel title="// parity · mobile vs desktop">
            <table className="data">
              <thead><tr><th>feature</th><th>desktop</th><th>mobile</th><th>parity</th></tr></thead>
              <tbody>
                {[
                  ["read · mission control",          "yes", "yes", "ok"],
                  ["read · signals + executions",     "yes", "yes (read)", "ok"],
                  ["read · positions",                 "yes", "yes (read)", "ok"],
                  ["control · kill switch",            "yes", "yes (biometric)", "ok"],
                  ["control · pause strategy",         "yes", "yes (biometric)", "ok"],
                  ["control · close position",         "yes", "no (deferred · paper-only ok)", "warn"],
                  ["control · enable live",            "no",  "no", "ok"],
                  ["control · config writes",          "yes (dual)", "no", "warn"],
                  ["narration · shift summary",        "yes", "yes", "ok"],
                  ["push · gate.block · drift.alert",  "—",   "yes", "ok"],
                  ["offline mode",                    "n/a", "read-cache 5m", "—"],
                ].map((r, i) => (
                  <tr key={i} className="row-hover">
                    <td className="mono">{r[0]}</td>
                    <td className="mono" style={{ color: "var(--text-mid)" }}>{r[1]}</td>
                    <td className="mono" style={{ color: "var(--text-mid)" }}>{r[2]}</td>
                    <td><Chip kind={r[3] === "ok" ? "ok" : r[3] === "warn" ? "warn" : null}>{r[3]}</Chip></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <Panel title="// build">
              <KVTable rows={[
                ["platform", "iOS 17+ · iPhone 13 and up"],
                ["distribution", "TestFlight · internal"],
                ["build", "0.4.1-rc2"],
                ["binary size", "11.4 MB"],
                ["cold start p99", "0.81s"],
                ["push provider", "apns2 · sandbox"],
                ["biometric", "FaceID / TouchID"],
                ["secrets storage", "keychain · access-after-first-unlock"],
                ["network egress", "vpn-only · internal mesh"],
              ]} />
            </Panel>
            <Panel title="// gate · before live">
              {[
                ["dangerous controls behind biometric+pin", "ok"],
                ["session lock @ 5min idle",                "ok"],
                ["jailbreak detection",                     "ok"],
                ["pin retry lockout",                       "ok"],
                ["push delivery e2e proof",                 "warn"],
                ["offline kill-switch fallback",            "warn"],
                ["legal · disclaimers + audit log access",  "warn"],
              ].map((r, i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: "1px solid var(--border)", alignItems: "center" }}>
                  <span className="mono" style={{ fontSize: 11.5 }}>{r[0]}</span>
                  <Chip kind={r[1] === "ok" ? "ok" : "warn"}>{r[1].toUpperCase()}</Chip>
                </div>
              ))}
            </Panel>
          </div>
        </div>
      </div>
    </div>
  );
}

window.SystemHealthPage = SystemHealthPage;
window.BuildValidationPage = BuildValidationPage;
window.MobileReadinessPage = MobileReadinessPage;
===== END FILE: pages-system.jsx =====

