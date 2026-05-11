// Inspect section: Trainer Monitor, Coverage/Atlas, Script Registry, Monitor Center, Audit Ledger
const { TRAINER_PRED, AUDIT, makeSpark, makeEquityPath } = window.AIBOT;

function TrainerMonitorPage() {
  const loss = makeEquityPath(900, 160, 96);
  return (
    <div>
      <PageHeader screen="11 Trainer Monitor" sub="hybrid-v4.2 · ckpt 0291 · step 184,201 · prediction stream"
        title="TRAINER MONITOR"
        chips={<><Chip kind="ok">TRAINING · LIVE</Chip><Chip kind="warn">DRIFT · 1 SYM</Chip><Chip>loss 0.0382</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(6, minmax(0,1fr))", gap: 12, marginBottom: 16 }}>
        {[
          { l: "step",        v: "184,201",   t: "var(--text)" },
          { l: "epoch",       v: "47 / 50",   t: "var(--text)" },
          { l: "loss",        v: "0.0382",    t: "var(--ok)" },
          { l: "val loss",    v: "0.0411",    t: "var(--ok)" },
          { l: "lr",          v: "3.2e-4",    t: "var(--text)" },
          { l: "tps",         v: "12,481",    t: "var(--text)" },
        ].map(k => (
          <div key={k.l} className="panel" style={{ padding: "12px 14px" }}>
            <span className="label-mono">{k.l}</span>
            <div className="kpi-num" style={{ fontSize: 18, marginTop: 6, color: k.t }}>{k.v}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,2fr) minmax(0,1fr)", gap: 16, marginBottom: 16 }}>
        <Panel title="// training loss · val loss · 96 steps">
          <svg viewBox="0 0 900 160" width="100%" height="160" preserveAspectRatio="none">
            {[0.25, 0.5, 0.75].map(p => <line key={p} x1="0" x2="900" y1={160 * p} y2={160 * p} stroke="var(--border)" strokeDasharray="2 3" />)}
            <path d={loss.d} stroke="var(--ok)" fill="none" strokeWidth="1.4" />
            <path d={makeEquityPath(900, 160, 96).d} stroke="var(--accent)" fill="none" strokeWidth="1.2" strokeDasharray="3 4" opacity="0.7" />
          </svg>
          <div className="mono" style={{ fontSize: 10, color: "var(--text-dim)", display: "flex", gap: 18, marginTop: 4 }}>
            <span><span style={{ color: "var(--ok)" }}>━</span> train loss</span>
            <span><span style={{ color: "var(--accent)" }}>┄</span> val loss</span>
          </div>
        </Panel>
        <Panel title="// model lineage">
          {[
            ["model_id", "hybrid-v4.2"],
            ["checkpoint", "0291"],
            ["base", "hybrid-v4.1-ckpt0188"],
            ["arch", "tcn-transformer-hybrid"],
            ["params", "12.4M"],
            ["feature schema", "v18 · 184 cols"],
            ["target", "fwd-return-15m · classified"],
            ["calibration", "platt + isotonic"],
            ["last promote", "2026-05-08 14:21 UTC"],
            ["sha256", "8be1…02af"],
            ["audit-pinned", "yes"],
          ].map(r => (
            <div key={r[0]} style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", borderBottom: "1px solid var(--border)" }}>
              <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>{r[0]}</span>
              <span className="mono" style={{ fontSize: 11, color: "var(--text)" }}>{r[1]}</span>
            </div>
          ))}
        </Panel>
      </div>

      <Panel title="// prediction monitor · per-symbol" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>symbol</th><th>accuracy</th><th>mae</th><th>brier</th><th>drift (KS)</th><th>last pub</th><th>calibration</th><th>verdict</th></tr></thead>
          <tbody>
            {TRAINER_PRED.map(p => {
              const acc = p.acc;
              const drift = p.drift;
              const stale = parseFloat(p.last) > 2.5;
              return (
                <tr key={p.sym} className="row-hover">
                  <td className="mono">{p.sym}</td>
                  <td className="mono">
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <div style={{ width: 60, height: 5, background: "var(--bg)", border: "1px solid var(--border)" }}>
                        <div style={{ width: `${(acc - 0.5) * 800}%`, height: "100%", background: acc >= 0.58 ? "var(--ok)" : "var(--accent)" }} />
                      </div>
                      <span>{acc.toFixed(3)}</span>
                    </div>
                  </td>
                  <td className="mono">{p.mae.toFixed(4)}</td>
                  <td className="mono">{p.brier.toFixed(3)}</td>
                  <td className="mono" style={{ color: drift > 0.15 ? "var(--block)" : drift > 0.1 ? "var(--accent)" : "var(--ok)" }}>{drift.toFixed(2)}</td>
                  <td className="mono" style={{ color: stale ? "var(--accent)" : "var(--text-dim)" }}>{p.last}</td>
                  <td><Chip kind={acc >= 0.58 ? "ok" : "warn"}>{acc >= 0.58 ? "calibrated" : "drift"}</Chip></td>
                  <td><Chip kind={drift > 0.15 ? "block" : "ok"}>{drift > 0.15 ? "HALT" : "OK"}</Chip></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// feature importance · top-12">
          {[
            ["ret_15m_zscore", 0.94], ["orderflow_imbalance_1m", 0.87], ["funding_skew_8h", 0.74],
            ["realized_vol_1h", 0.71], ["atr_pct_4h", 0.65], ["macd_div_4h", 0.61],
            ["oi_delta_15m", 0.58], ["taker_buy_ratio_5m", 0.54], ["vwap_dev_1h", 0.49],
            ["btc_corr_1h", 0.45], ["regime_flag", 0.41], ["news_sentiment_1h", 0.28],
          ].map(([k, v]) => (
            <div key={k} style={{ display: "grid", gridTemplateColumns: "180px 1fr 40px", gap: 10, padding: "4px 0", alignItems: "center" }}>
              <span className="mono" style={{ fontSize: 11 }}>{k}</span>
              <div style={{ height: 5, background: "var(--bg)", border: "1px solid var(--border)" }}>
                <div style={{ width: `${v * 100}%`, height: "100%", background: "var(--accent)" }} />
              </div>
              <span className="mono" style={{ fontSize: 10, textAlign: "right", color: "var(--text-dim)" }}>{v.toFixed(2)}</span>
            </div>
          ))}
        </Panel>
        <Panel title="// training events">
          {[
            { t: "13:38:41", k: "checkpoint.save", d: "ckpt 0291 → store · 184,201" },
            { t: "13:22:11", k: "schema.bump",    d: "feature schema v18 (184 cols) · audit OK" },
            { t: "12:48:02", k: "drift.alert",    d: "SOL-USDT drift > 0.15 · auto-pause armed" },
            { t: "12:12:51", k: "calibration",    d: "platt+isotonic refit · brier ↓ 0.011" },
            { t: "11:48:33", k: "epoch.advance",  d: "epoch 46 → 47 · loss 0.0411 → 0.0382" },
            { t: "10:11:42", k: "data.window",    d: "rolled 14d → 30d, replay 3,212k bars" },
          ].map((e, i) => (
            <div key={i} style={{ display: "grid", gridTemplateColumns: "70px 130px 1fr", gap: 10, padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
              <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>{e.t}</span>
              <span className="mono" style={{ fontSize: 11, color: "var(--accent)" }}>{e.k}</span>
              <span className="mono" style={{ fontSize: 11 }}>{e.d}</span>
            </div>
          ))}
        </Panel>
      </div>
    </div>
  );
}

function CoverageAtlasPage() {
  const sections = [
    { tier: "A", group: "TRAINER", items: [
      ["data.ingestion",      "raw-reviewed", "ok"],
      ["feature.materialize", "raw-reviewed", "ok"],
      ["target.labeling",     "raw-reviewed", "ok"],
      ["model.train",         "raw-reviewed", "ok"],
      ["model.eval",          "raw-reviewed", "ok"],
      ["model.calibrate",     "raw-reviewed", "ok"],
      ["model.promote",       "raw-reviewed", "ok"],
      ["prediction.publish",  "raw-reviewed", "ok"],
    ]},
    { tier: "A", group: "ORCHESTRATOR", items: [
      ["signal.compose",      "raw-reviewed", "ok"],
      ["signal.attribution",  "raw-reviewed", "ok"],
      ["queue.bounded",       "raw-reviewed", "ok"],
      ["dedup.window",        "raw-reviewed", "ok"],
      ["lineage.chain",       "raw-reviewed", "ok"],
    ]},
    { tier: "A", group: "RISK GATEWAY", items: [
      ["gate.contract",       "raw-reviewed", "ok"],
      ["live.flag",           "raw-reviewed", "ok"],
      ["cross.margin.block",  "raw-reviewed", "ok"],
      ["leverage.cap",        "raw-reviewed", "ok"],
      ["adjust.leverage",     "evidence-pending", "warn"],
      ["kill.switch",         "raw-reviewed", "ok"],
    ]},
    { tier: "A", group: "EXECUTION", items: [
      ["paper.adapter",       "raw-reviewed", "ok"],
      ["replay.adapter",      "raw-reviewed", "ok"],
      ["fill.semantics",      "raw-reviewed", "ok"],
      ["ledger.cost-basis",   "raw-reviewed", "ok"],
      ["live.adapter",        "blocked",      "block"],
    ]},
    { tier: "B", group: "AUDIT", items: [
      ["chain.integrity",     "raw-reviewed", "ok"],
      ["hash.algo",           "raw-reviewed", "ok"],
      ["forensic.replay",     "evidence-pending", "warn"],
    ]},
    { tier: "B", group: "AI LAYER", items: [
      ["claude.admin",        "raw-reviewed", "ok"],
      ["ollama.summary",      "evidence-pending", "warn"],
      ["codex.review",        "evidence-pending", "warn"],
    ]},
  ];
  return (
    <div>
      <PageHeader screen="12 Coverage Atlas" sub="trainer.atlas · raw evidence coverage · audit-linked" title="COVERAGE / ATLAS"
        chips={<><Chip kind="ok">TIER A · 31/31</Chip><Chip kind="warn">TIER B · 5/8</Chip><Chip>OVERALL 36/39</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12, marginBottom: 16 }}>
        {[
          { l: "raw-reviewed",     v: "31", t: "var(--ok)" },
          { l: "evidence-pending", v: "3",  t: "var(--accent)" },
          { l: "blocked",          v: "1",  t: "var(--block)" },
          { l: "stub",             v: "0",  t: "var(--text)" },
        ].map(k => (
          <div key={k.l} className="panel" style={{ padding: "12px 14px" }}>
            <span className="label-mono">{k.l}</span>
            <div className="kpi-num" style={{ fontSize: 24, marginTop: 6, color: k.t }}>{k.v}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0,1fr))", gap: 16 }}>
        {sections.map(g => (
          <Panel key={g.group} title={`// ${g.group} · tier ${g.tier}`}>
            {g.items.map(([k, status, tone]) => (
              <div key={k} style={{ display: "grid", gridTemplateColumns: "1fr auto auto", gap: 10, padding: "5px 0", borderBottom: "1px solid var(--border)", alignItems: "center" }}>
                <span className="mono" style={{ fontSize: 12 }}>{k}</span>
                <span className="mono" style={{ fontSize: 10, color: tone === "ok" ? "var(--ok)" : tone === "warn" ? "var(--accent)" : "var(--block)" }}>{status}</span>
                <Chip kind={tone === "ok" ? "ok" : tone === "warn" ? "warn" : "block"}>{tone === "ok" ? "✓" : tone === "warn" ? "!" : "✗"}</Chip>
              </div>
            ))}
          </Panel>
        ))}
      </div>
    </div>
  );
}

function ScriptRegistryPage() {
  const ROWS = [
    { id: "S-0001", path: "scripts/trainer/train_loop.py",       v: "1.18.0", hash: "a019…41bc", role: "trainer",     last: "13:38:41", state: "MATCH" },
    { id: "S-0002", path: "scripts/trainer/eval_pipeline.py",   v: "1.11.2", hash: "f2c4…91ae", role: "trainer",     last: "13:33:01", state: "MATCH" },
    { id: "S-0003", path: "scripts/trainer/calibrate.py",       v: "1.04.1", hash: "b8d1…77c0", role: "trainer",     last: "12:48:11", state: "MATCH" },
    { id: "S-0004", path: "scripts/orchestrator/compose.py",    v: "2.04.0", hash: "44ee…ae21", role: "orchestrator",last: "13:42:11", state: "MATCH" },
    { id: "S-0005", path: "scripts/orchestrator/lineage.py",    v: "2.01.0", hash: "31ba…b7c4", role: "orchestrator",last: "13:41:58", state: "MATCH" },
    { id: "S-0006", path: "scripts/risk/gateway.py",            v: "3.02.1", hash: "00aa…1e7f", role: "risk",         last: "13:42:11", state: "MATCH" },
    { id: "S-0007", path: "scripts/risk/policies.yaml",         v: "0.18.0", hash: "9d72…5b8a", role: "risk-policy",  last: "13:11:01", state: "DRIFT" },
    { id: "S-0008", path: "scripts/execution/paper.py",         v: "1.07.0", hash: "5cef…83b1", role: "execution",   last: "13:42:01", state: "MATCH" },
    { id: "S-0009", path: "scripts/execution/replay.py",        v: "1.03.2", hash: "1100…aaff", role: "execution",   last: "13:34:21", state: "MATCH" },
    { id: "S-0010", path: "scripts/audit/chain.py",             v: "1.21.0", hash: "7a02…be11", role: "audit",       last: "13:42:11", state: "MATCH" },
    { id: "S-0011", path: "scripts/ai/claude_admin.py",         v: "0.08.0", hash: "1182…3322", role: "ai",          last: "13:21:41", state: "DRIFT" },
    { id: "S-0012", path: "scripts/ai/ollama_summary.py",        v: "0.04.0", hash: "5642…ee22", role: "ai",          last: "13:01:12", state: "DRIFT" },
    { id: "S-0013", path: "scripts/ai/codex_review.py",          v: "0.02.0", hash: "3334…ab19", role: "ai",          last: "12:21:31", state: "STUB"  },
    { id: "S-0014", path: "scripts/scaffold/validate.py",       v: "1.04.0", hash: "8be1…02af", role: "scaffold",    last: "13:38:41", state: "MATCH" },
    { id: "S-0015", path: "scripts/redis/migrate_namespaces.py", v: "1.02.0", hash: "abcd…1234", role: "redis",       last: "10:18:01", state: "MATCH" },
    { id: "S-0016", path: "scripts/postgres/schema.sql",        v: "0.31.0", hash: "ef21…7711", role: "postgres",    last: "10:18:01", state: "MATCH" },
  ];
  return (
    <div>
      <PageHeader screen="13 Script Registry" sub="canonical scripts · sha256-pinned · runtime hash compared" title="SCRIPT REGISTRY"
        chips={<><Chip kind="ok">13 MATCH</Chip><Chip kind="warn">3 DRIFT</Chip><Chip kind="block">0 MISSING</Chip></>} />

      <div style={{ display: "flex", gap: 10, marginBottom: 12 }}>
        <input className="input" placeholder="search path, hash, role…" style={{ width: 360 }} />
        <Chip>ROLE · all</Chip><Chip>STATE · all</Chip>
        <span style={{ flex: 1 }} />
        <button className="btn">RE-HASH</button>
        <button className="btn">EXPORT MANIFEST</button>
      </div>

      <Panel title="// canonical scripts · 16 of 247" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>id</th><th>path</th><th>role</th><th>v</th><th>sha256</th><th>last seen</th><th>state</th><th></th></tr></thead>
          <tbody>
            {ROWS.map(r => (
              <tr key={r.id} className="row-hover">
                <td className="mono">{r.id}</td>
                <td className="mono" style={{ fontSize: 11 }}>{r.path}</td>
                <td className="mono" style={{ color: "var(--text-mid)" }}>{r.role}</td>
                <td className="mono">{r.v}</td>
                <td className="mono" style={{ color: "var(--text-dim)", fontSize: 10.5 }}>{r.hash}</td>
                <td className="mono" style={{ color: "var(--text-dim)" }}>{r.last}</td>
                <td><Chip kind={r.state === "MATCH" ? "ok" : r.state === "DRIFT" ? "warn" : r.state === "STUB" ? "warn" : "block"}>{r.state}</Chip></td>
                <td><button className="btn">diff</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

function MonitorCenterPage() {
  const MONS = [
    ["redis.ns.aibotv2",      "ok",    "keys 12,481 · evicted 0",                "00:00:00.2"],
    ["redis.legacy.write",    "ok",    "0 writes detected · isolation enforced", "00:00:00.4"],
    ["postgres.lag",          "ok",    "lag 0ms · pgbouncer 12 idle",            "00:00:00.8"],
    ["audit.chain",            "ok",    "1,204,481 links · 0 breaks",             "00:00:00.6"],
    ["orchestrator.queue",    "ok",    "0 stuck · backpressure 0%",              "00:00:00.7"],
    ["trainer.heartbeat",     "ok",    "5 / 5 workers ack",                       "00:00:01.4"],
    ["risk.gate.latency",     "ok",    "p99 1.41ms · p999 2.18ms",                "00:00:00.3"],
    ["execution.replay.det",  "ok",    "byte-identical vs golden",                "00:00:00.5"],
    ["live.adapter.lock",     "block", "armed · operator approval required",      "00:00:00.3"],
    ["model.drift.ks",        "warn",  "SOL-USDT KS 0.18 > 0.15",                 "00:00:02.1"],
    ["feature.freshness",     "warn",  "11 symbols > 2.5s in last hour",          "00:00:01.0"],
    ["claude.verify.lag",     "warn",  "3 ollama packets unverified",             "00:00:11.0"],
    ["mobile.readiness.beta", "dim",   "iOS beta build · n/a yet",                "00:11:42.0"],
    ["build.scaffold.cron",   "ok",    "cron 5m · last 14:02 · PASS",             "00:01:08.0"],
  ];
  return (
    <div>
      <PageHeader screen="14 Monitor Center" sub="active monitors · alert rules · escalation" title="MONITOR CENTER"
        chips={<><Chip kind="ok">11 OK</Chip><Chip kind="warn">3 WARN</Chip><Chip kind="block">1 BLOCK</Chip></>} />

      <Panel title="// monitors · 14 active" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>monitor</th><th>state</th><th>detail</th><th>since</th><th>escalation</th><th></th></tr></thead>
          <tbody>
            {MONS.map(([name, st, det, since], i) => (
              <tr key={name} className="row-hover">
                <td className="mono">{name}</td>
                <td><Chip kind={st === "ok" ? "ok" : st === "warn" ? "warn" : st === "block" ? "block" : null}>{st.toUpperCase()}</Chip></td>
                <td className="mono" style={{ fontSize: 11.5, color: "var(--text-mid)" }}>{det}</td>
                <td className="mono" style={{ color: "var(--text-dim)" }}>{since}</td>
                <td className="mono" style={{ fontSize: 11, color: "var(--text-mid)" }}>{i % 4 === 0 ? "page operator" : i % 4 === 1 ? "slack #ai-bot-ops" : i % 4 === 2 ? "claude.admin verify" : "log only"}</td>
                <td><button className="btn">silence</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

function AuditLedgerPage() {
  const more = Array.from({ length: 14 }, (_, i) => ({
    seq: `1,204,${(465 - i).toString().padStart(3,"0")}`,
    t: `13:41:${String(45 - i).padStart(2, "0")}.${String((i*131)%999).padStart(3,"0")}`,
    actor: ["orchestrator","risk-gateway","trainer","execution","operator","audit"][i % 6],
    action: ["signal.publish","gate.allow","prediction.publish","paper.fill","gate.block","config.update","feature.refresh","ledger.lot"][i % 8],
    target: `01HW9F${(i*3).toString(36).toUpperCase().slice(0,4)}`,
    prev: `${(0x1000 + i*7).toString(16)}…${(0x8000 - i*3).toString(16)}`,
    curr: `${(0x1100 + i*11).toString(16)}…${(0x8800 - i*7).toString(16)}`,
    verdict: i === 4 || i === 9 ? "block" : "ok",
  }));
  const ALL = [...AUDIT, ...more];
  return (
    <div>
      <PageHeader screen="15 Audit Ledger" sub="append-only chain · sha256-linked · forensic-grade"
        title="AUDIT LEDGER"
        chips={<><Chip kind="ok">CHAIN OK · 0 BREAKS</Chip><Chip>1,204,481 LINKS</Chip><Chip>head a017…23dd</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12, marginBottom: 16 }}>
        {[
          { l: "links · all-time",   v: "1,204,481", t: "var(--text)" },
          { l: "links · 24h",        v: "187,402",   t: "var(--text)" },
          { l: "chain breaks",       v: "0",         t: "var(--ok)" },
          { l: "forensic replays",   v: "12 / 12",   t: "var(--ok)" },
        ].map(k => (
          <div key={k.l} className="panel" style={{ padding: "12px 14px" }}>
            <span className="label-mono">{k.l}</span>
            <div className="kpi-num" style={{ fontSize: 22, marginTop: 6, color: k.t }}>{k.v}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", gap: 10, marginBottom: 12 }}>
        <input className="input" placeholder="search target, hash, actor…" style={{ width: 360 }} />
        <Chip>ACTOR · all</Chip><Chip>ACTION · all</Chip><Chip>VERDICT · all</Chip>
        <span style={{ flex: 1 }} />
        <button className="btn">VERIFY CHAIN</button>
        <button className="btn">EXPORT NDJSON</button>
      </div>

      <Panel title="// chain · tail 22" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>seq</th><th>time</th><th>actor</th><th>action</th><th>target</th><th>prev_hash</th><th>curr_hash</th><th>verdict</th></tr></thead>
          <tbody>
            {ALL.map(r => (
              <tr key={r.seq} className="row-hover">
                <td className="mono">{r.seq}</td>
                <td className="mono" style={{ color: "var(--text-dim)" }}>{r.t}</td>
                <td className="mono" style={{ color: "var(--text-mid)" }}>{r.actor}</td>
                <td className="mono">{r.action}</td>
                <td className="mono" style={{ color: "var(--accent)" }}>{r.target}</td>
                <td className="mono" style={{ color: "var(--text-dim)", fontSize: 10.5 }}>{r.prev}</td>
                <td className="mono" style={{ color: "var(--text)", fontSize: 10.5 }}>{r.curr}</td>
                <td><Chip kind={r.verdict === "ok" ? "ok" : "block"}>{r.verdict.toUpperCase()}</Chip></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

window.TrainerMonitorPage = TrainerMonitorPage;
window.CoverageAtlasPage = CoverageAtlasPage;
window.ScriptRegistryPage = ScriptRegistryPage;
window.MonitorCenterPage = MonitorCenterPage;
window.AuditLedgerPage = AuditLedgerPage;
===== END FILE: pages-inspect.jsx =====

