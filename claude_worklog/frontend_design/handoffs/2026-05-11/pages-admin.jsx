// Admin section: Live Readiness, Config/Strategy/Trainer/Orchestrator/Execution Admin
const { RISK_RULES } = window.AIBOT;

function LiveReadinessPage() {
  const ITEMS = [
    { n: 1,  k: "live.adapter.implementation",       s: "block", e: "scripts/execution/live.py is stub", who: "execution",   est: "P0" },
    { n: 2,  k: "live.adapter.contract.tests",       s: "block", e: "0/24 contract tests written",      who: "execution",   est: "P0" },
    { n: 3,  k: "exchange.connector.matrix",         s: "block", e: "binance + bybit + okx connector heartbeats", who: "execution", est: "P0" },
    { n: 4,  k: "subaccount.isolation",              s: "warn",  e: "ledger supports it, no e2e proof",  who: "execution",   est: "P1" },
    { n: 5,  k: "kill.switch.physical",              s: "warn",  e: "redis-backed, no hardware backstop", who: "risk",        est: "P1" },
    { n: 6,  k: "operator.dual-control",             s: "block", e: "2-of-3 sign-off flow not wired",    who: "risk",        est: "P0" },
    { n: 7,  k: "leverage.cap.live",                 s: "ok",    e: "policy rev 18 · 1x · pinned",       who: "risk",        est: "—"  },
    { n: 8,  k: "cross.margin.in.live",              s: "ok",    e: "ISOLATED enforced at gate",         who: "risk",        est: "—"  },
    { n: 9,  k: "feature.freshness.budget",          s: "warn",  e: "11 syms > 2.5s/h · burn rate 1.4x", who: "trainer",     est: "P1" },
    { n: 10, k: "model.drift.halt",                  s: "warn",  e: "auto-pause armed, never fired",     who: "trainer",     est: "P1" },
    { n: 11, k: "audit.chain.live.witness",          s: "warn",  e: "external witness service not wired", who: "audit",       est: "P1" },
    { n: 12, k: "ops.runbook.coverage",              s: "warn",  e: "21/27 scenarios documented",        who: "ops",         est: "P2" },
    { n: 13, k: "mobile.kill.switch.parity",         s: "ok",    e: "iOS shortcut configured · paper",   who: "ops",         est: "—"  },
    { n: 14, k: "rollback.previous.checkpoint",      s: "ok",    e: "verified · ckpt 0290 reproducible", who: "trainer",     est: "—"  },
  ];
  const ok = ITEMS.filter(x => x.s === "ok").length;
  const warn = ITEMS.filter(x => x.s === "warn").length;
  const block = ITEMS.filter(x => x.s === "block").length;
  return (
    <div>
      <PageHeader screen="16 Live Readiness" sub="14-item gate · live-trading remains blocked until all green" title="LIVE READINESS"
        chips={<><Chip kind="block">LIVE · BLOCKED</Chip><Chip kind="ok">{ok}/14 GREEN</Chip><Chip kind="warn">{warn} WARN</Chip><Chip kind="block">{block} BLOCK</Chip></>} />

      <div className="panel hatch" style={{ padding: 18, marginBottom: 16, borderLeft: "3px solid var(--block)" }}>
        <Eyebrow style={{ color: "var(--block)" }}>// readiness verdict</Eyebrow>
        <div className="cond" style={{ fontSize: 22, marginTop: 4, color: "var(--block)" }}>NOT READY · 5 of 14 items blocking</div>
        <div className="mono" style={{ fontSize: 11.5, color: "var(--text-mid)", marginTop: 6, lineHeight: 1.6 }}>
          live trading cannot be enabled. all P0 items must transition to GREEN with raw evidence pinned in audit. operator dual-control sign-off
          is required after the technical gate clears. an attempt to override this gate from automation will be rejected and audit-logged.
        </div>
      </div>

      <Panel title="// readiness checklist" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>#</th><th>item</th><th>state</th><th>evidence</th><th>owner</th><th>priority</th><th></th></tr></thead>
          <tbody>
            {ITEMS.map(it => (
              <tr key={it.n} className="row-hover">
                <td className="mono" style={{ color: "var(--text-dim)" }}>{String(it.n).padStart(2,"0")}</td>
                <td className="mono">{it.k}</td>
                <td><Chip kind={it.s === "ok" ? "ok" : it.s === "warn" ? "warn" : "block"}>{it.s.toUpperCase()}</Chip></td>
                <td className="mono" style={{ fontSize: 11, color: "var(--text-mid)" }}>{it.e}</td>
                <td className="mono" style={{ color: "var(--text-mid)" }}>{it.who}</td>
                <td className="mono" style={{ color: it.est === "P0" ? "var(--block)" : it.est === "P1" ? "var(--accent)" : "var(--text-dim)" }}>{it.est}</td>
                <td><button className="btn">open evidence</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <Panel title="// dual-control sign-off · queue" style={{ marginTop: 16 }}>
        <div className="mono" style={{ fontSize: 11.5, color: "var(--text-mid)", marginBottom: 10 }}>
          required: <strong style={{ color: "var(--text)" }}>2 of 3</strong> approvers, distinct roles, not the requester
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0,1fr))", gap: 10 }}>
          {[
            { who: "wali1984",   role: "operator",   state: "REQUESTED" },
            { who: "—",           role: "engineering",state: "PENDING" },
            { who: "—",           role: "risk",       state: "PENDING" },
          ].map(p => (
            <div key={p.role} className="panel" style={{ padding: 12, background: "var(--bg)" }}>
              <Eyebrow>{p.role}</Eyebrow>
              <div className="mono" style={{ marginTop: 4 }}>{p.who}</div>
              <Chip kind={p.state === "REQUESTED" ? "warn" : null} style={{ marginTop: 8 }}>{p.state}</Chip>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

function KVTable({ rows }) {
  return (
    <table className="data">
      <tbody>
        {rows.map(([k, v, t]) => (
          <tr key={k}>
            <td className="mono" style={{ color: "var(--text-dim)", width: "40%", fontSize: 11.5 }}>{k}</td>
            <td className="mono" style={{ color: t || "var(--text)", fontSize: 11.5 }}>{v}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ConfigAdminPage() {
  return (
    <div>
      <PageHeader screen="17 Config Admin" sub="layered config · policy rev 18 · audit-pinned · dual-control writes" title="CONFIG ADMIN"
        chips={<><Chip kind="ok">REV 18 · CLEAN</Chip><Chip>3 pending edits</Chip><Chip kind="warn">RBAC · admin</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16 }}>
        <Panel title="// runtime · paper">
          <KVTable rows={[
            ["mode", "paper"],
            ["live.enabled", "false", "var(--block)"],
            ["adapter", "replay-v2"],
            ["leverage.cap.paper", "3x"],
            ["leverage.cap.live", "1x", "var(--text-mid)"],
            ["margin.mode", "ISOLATED"],
            ["kill.switch", "ARMED", "var(--accent)"],
            ["hedge.enabled", "false"],
            ["dca.enabled", "false"],
            ["feature.freshness.budget.s", "2.5"],
            ["dedup.window.h", "24"],
          ]} />
        </Panel>
        <Panel title="// thresholds">
          <KVTable rows={[
            ["confidence.min", "0.60"],
            ["confidence.hot", "0.80"],
            ["atr.stop.min", "1.5x"],
            ["atr.stop.max", "3.5x"],
            ["risk.per.trade.pct", "0.50%"],
            ["max.concurrent.positions", "8"],
            ["max.gross.exposure.pct", "60%"],
            ["max.daily.loss.pct", "1.50%"],
            ["drift.ks.halt", "0.15"],
            ["latency.gate.budget.ms", "2.50"],
            ["latency.publish.budget.ms", "5.00"],
          ]} />
        </Panel>
      </div>

      <Panel title="// pending edits · awaiting dual-control" style={{ marginTop: 16 }} bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>id</th><th>key</th><th>from</th><th>to</th><th>requester</th><th>approver</th><th>state</th><th></th></tr></thead>
          <tbody>
            {[
              ["E-211", "confidence.min", "0.60", "0.62", "wali1984", "—", "PENDING"],
              ["E-210", "feature.freshness.budget.s", "2.5", "2.0", "wali1984", "—", "PENDING"],
              ["E-209", "atr.stop.min", "1.5x", "1.8x", "ops",      "wali1984", "APPROVED"],
            ].map(r => (
              <tr key={r[0]} className="row-hover">
                {r.slice(0,6).map((c,i) => <td key={i} className="mono">{c}</td>)}
                <td><Chip kind={r[6] === "APPROVED" ? "ok" : "warn"}>{r[6]}</Chip></td>
                <td><button className="btn">{r[6] === "PENDING" ? "approve" : "apply"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

function StrategyAdminPage() {
  const ROWS = [
    { id: "mass-momentum-v3", v: "rev 41", st: "ACTIVE", w: "BTC,ETH,SOL,AVAX,ARB", pnl: "+$2,118", live: "blocked" },
    { id: "mean-revert-v2",   v: "rev 22", st: "ACTIVE", w: "BNB,MATIC,DOGE", pnl: "+$612",  live: "blocked" },
    { id: "breakout-atr-v1",  v: "rev 7",  st: "ACTIVE", w: "LINK,ATOM", pnl: "+$382",  live: "blocked" },
    { id: "funding-skew-v1",  v: "rev 11", st: "ACTIVE", w: "BTC,ETH", pnl: "+$208",  live: "blocked" },
    { id: "regime-flip-v0",   v: "rev 3",  st: "PAUSED", w: "—",       pnl: "−$223",  live: "blocked" },
    { id: "spread-arb-v0",    v: "rev 1",  st: "DRAFT",  w: "—",       pnl: "—",      live: "blocked" },
  ];
  return (
    <div>
      <PageHeader screen="18 Strategy Admin" sub="strategy registry · versions · weight allocation · live disabled" title="STRATEGY ADMIN"
        chips={<><Chip kind="ok">4 ACTIVE</Chip><Chip kind="warn">1 PAUSED</Chip><Chip>1 DRAFT</Chip></>} />

      <Panel title="// strategies" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>strategy</th><th>version</th><th>state</th><th>universe</th><th>paper pnl 7d</th><th>live</th><th></th></tr></thead>
          <tbody>
            {ROWS.map(r => (
              <tr key={r.id} className="row-hover">
                <td className="mono"><strong>{r.id}</strong></td>
                <td className="mono">{r.v}</td>
                <td><Chip kind={r.st === "ACTIVE" ? "ok" : r.st === "PAUSED" ? "warn" : null}>{r.st}</Chip></td>
                <td className="mono" style={{ color: "var(--text-mid)", fontSize: 11 }}>{r.w}</td>
                <td className="mono" style={{ color: r.pnl.startsWith("+") ? "var(--ok)" : r.pnl.startsWith("−") ? "var(--block)" : "var(--text-dim)" }}>{r.pnl}</td>
                <td><Chip kind="block">{r.live}</Chip></td>
                <td><button className="btn">edit</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// weight allocation · paper">
          {[
            { k: "mass-momentum-v3", w: 50 },
            { k: "mean-revert-v2",   w: 20 },
            { k: "breakout-atr-v1",  w: 15 },
            { k: "funding-skew-v1",  w: 10 },
            { k: "regime-flip-v0",   w:  5 },
          ].map(s => (
            <div key={s.k} style={{ padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span className="mono" style={{ fontSize: 12 }}>{s.k}</span>
                <span className="mono" style={{ fontSize: 12, color: "var(--accent)" }}>{s.w}%</span>
              </div>
              <div style={{ marginTop: 5, height: 5, background: "var(--bg)", border: "1px solid var(--border)" }}>
                <div style={{ width: `${s.w}%`, height: "100%", background: "var(--accent)" }} />
              </div>
            </div>
          ))}
        </Panel>
        <Panel title="// composition rules">
          {[
            ["max strategies per signal", "1"],
            ["correlation cap (per sym)", "0.65"],
            ["overlap policy", "first-wins · attribution preserved"],
            ["promotion gate", "≥ 30d paper · sharpe ≥ 1.0 · dd ≤ 5%"],
            ["demote gate", "rolling sharpe < 0.3 · 7d window"],
            ["sandbox.draft.signals", "log-only"],
          ].map(([k, v]) => (
            <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
              <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>{k}</span>
              <span className="mono" style={{ fontSize: 11, color: "var(--text)" }}>{v}</span>
            </div>
          ))}
        </Panel>
      </div>
    </div>
  );
}

function TrainerAdminPage() {
  return (
    <div>
      <PageHeader screen="19 Trainer Admin" sub="hyperparams · scheduler · checkpoints · promote / rollback" title="TRAINER ADMIN"
        chips={<><Chip kind="ok">TRAINING · LIVE</Chip><Chip>ckpt 0291</Chip><Chip>5/5 workers</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16 }}>
        <Panel title="// hyperparameters">
          <KVTable rows={[
            ["architecture", "tcn-transformer-hybrid"],
            ["base.lr", "3.2e-4"],
            ["warmup.steps", "2,000"],
            ["scheduler", "cosine · t_max 50k"],
            ["batch.size", "256"],
            ["seq.len", "96"],
            ["dropout", "0.10"],
            ["weight.decay", "1e-5"],
            ["grad.clip", "1.00"],
            ["optimizer", "adamw"],
            ["loss", "focal · α 0.25 · γ 2"],
            ["calibration", "platt + isotonic"],
          ]} />
        </Panel>
        <Panel title="// data + features">
          <KVTable rows={[
            ["data.window.days", "30"],
            ["bar.interval", "1m"],
            ["symbols.train", "BTC,ETH,SOL,AVAX,BNB,ARB,MATIC,DOGE,LINK,ATOM"],
            ["features.schema", "v18 · 184 cols"],
            ["target", "fwd-return-15m · 5-class"],
            ["augment", "noise σ 0.01 · shuffle off"],
            ["val.split", "rolling 7d"],
            ["snapshot.cadence.steps", "1,000"],
            ["max.checkpoints.retain", "12"],
          ]} />
        </Panel>
      </div>

      <Panel title="// checkpoints" style={{ marginTop: 16 }} bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>ckpt</th><th>step</th><th>train</th><th>val</th><th>sharpe</th><th>brier</th><th>promoted</th><th>sha256</th><th></th></tr></thead>
          <tbody>
            {[
              ["0291","184,201","0.0382","0.0411","1.84","0.198","yes · ACTIVE","8be1…02af","var(--ok)"],
              ["0290","183,201","0.0388","0.0419","1.81","0.201","rollback target","f2c4…91ae",""],
              ["0289","182,201","0.0394","0.0421","1.78","0.204","no","a019…41bc",""],
              ["0288","181,201","0.0401","0.0427","1.74","0.208","no","44ee…ae21",""],
              ["0287","180,201","0.0418","0.0444","1.61","0.212","no · DRIFT","31ba…b7c4","var(--accent)"],
              ["0286","179,201","0.0431","0.0458","1.42","0.219","no · DROPPED","00aa…1e7f","var(--block)"],
            ].map(r => (
              <tr key={r[0]} className="row-hover">
                {r.slice(0,7).map((c,i) => <td key={i} className="mono" style={{ color: i === 6 ? r[8] : i === 0 ? "var(--accent)" : "var(--text)" }}>{c}</td>)}
                <td className="mono" style={{ color: "var(--text-dim)", fontSize: 11 }}>{r[7]}</td>
                <td><button className="btn">{r[6].includes("ACTIVE") ? "active" : r[6].includes("DROPPED") ? "—" : "promote"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

function OrchestratorAdminPage() {
  return (
    <div>
      <PageHeader screen="20 Orchestrator Admin" sub="signal composition · attribution · queue · lineage" title="ORCHESTRATOR ADMIN"
        chips={<><Chip kind="ok">9.4/s</Chip><Chip kind="ok">0 STUCK</Chip><Chip>queue 0</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12, marginBottom: 16 }}>
        {[
          { l: "throughput",       v: "9.4 /s",    t: "var(--ok)" },
          { l: "queue depth",       v: "0",         t: "var(--ok)" },
          { l: "stuck",            v: "0",         t: "var(--ok)" },
          { l: "publish p99",       v: "3.1 ms",   t: "var(--text)" },
        ].map(k => (
          <div key={k.l} className="panel" style={{ padding: "12px 14px" }}>
            <span className="label-mono">{k.l}</span>
            <div className="kpi-num" style={{ fontSize: 22, marginTop: 6, color: k.t }}>{k.v}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16 }}>
        <Panel title="// composition rules">
          <KVTable rows={[
            ["lineage.required", "model_id + checkpoint + features_hash + policy_rev"],
            ["attribution.required", "yes (rejects without)"],
            ["signal_id.scheme", "uuidv7"],
            ["dedup.key", "(symbol, side, model_id, bar_bucket)"],
            ["dedup.window", "24h"],
            ["bounded.queue", "10,000"],
            ["backpressure", "shed lowest-confidence first"],
            ["multi-strategy.policy", "first-wins · log losers"],
          ]} />
        </Panel>
        <Panel title="// publish topics">
          <KVTable rows={[
            ["signals.published", "→ risk-gateway"],
            ["signals.blocked",   "→ audit + monitor"],
            ["fills.confirmed",   "→ ledger + audit"],
            ["predictions.raw",   "→ feature-store snapshot"],
            ["health.heartbeat",  "→ monitor-center · 1s"],
            ["redis.namespace",   "aibotv2:*"],
            ["postgres.tables",   "signals, gates, fills, lots, audit"],
          ]} />
        </Panel>
      </div>
    </div>
  );
}

function ExecutionAdminPage() {
  return (
    <div>
      <PageHeader screen="21 Execution Admin" sub="adapters · venues · subaccounts · order routing · live disabled" title="EXECUTION ADMIN"
        chips={<><Chip kind="paper">ACTIVE · replay-v2</Chip><Chip kind="block">LIVE · BLOCKED</Chip></>} />

      <Panel title="// adapters" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>adapter</th><th>kind</th><th>state</th><th>venue</th><th>last fill</th><th>latency p99</th><th>fees</th><th></th></tr></thead>
          <tbody>
            {[
              { a: "replay-v2",       k: "paper",   s: "ACTIVE",   v: "synthetic",     lf: "13:42:01", lp: "0.81ms",  fe: "exchange-mirror", st: "ok" },
              { a: "paper-v1",        k: "paper",   s: "STANDBY",  v: "synthetic",     lf: "—",         lp: "—",       fe: "exchange-mirror", st: "" },
              { a: "binance-spot",    k: "live",    s: "BLOCKED",  v: "binance-spot",  lf: "—",         lp: "—",       fe: "tier-1",          st: "block" },
              { a: "bybit-perp",      k: "live",    s: "BLOCKED",  v: "bybit-perp",    lf: "—",         lp: "—",       fe: "vip-3",           st: "block" },
              { a: "okx-spot",        k: "live",    s: "BLOCKED",  v: "okx-spot",      lf: "—",         lp: "—",       fe: "tier-1",          st: "block" },
              { a: "ccxt-fallback",   k: "live",    s: "STUB",     v: "—",             lf: "—",         lp: "—",       fe: "—",                st: "warn" },
            ].map(r => (
              <tr key={r.a} className="row-hover">
                <td className="mono"><strong>{r.a}</strong></td>
                <td className="mono">{r.k}</td>
                <td><Chip kind={r.st === "ok" ? "ok" : r.st === "block" ? "block" : r.st === "warn" ? "warn" : null}>{r.s}</Chip></td>
                <td className="mono" style={{ color: "var(--text-mid)" }}>{r.v}</td>
                <td className="mono" style={{ color: "var(--text-dim)" }}>{r.lf}</td>
                <td className="mono">{r.lp}</td>
                <td className="mono" style={{ color: "var(--text-mid)" }}>{r.fe}</td>
                <td><button className="btn">configure</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// routing policy">
          <KVTable rows={[
            ["primary.adapter (paper)", "replay-v2"],
            ["primary.adapter (live)",  "— (blocked)"],
            ["fallback", "paper-v1"],
            ["order.type.default", "LIMIT · IOC"],
            ["slippage.cap.bps", "5.0"],
            ["partial.fill.policy", "accept · ledger lot per fill"],
            ["reject.on.exchange.error", "true"],
            ["retry.max", "0 (paper) · 0 (live · blocked)"],
          ]} />
        </Panel>
        <Panel title="// fees model">
          <KVTable rows={[
            ["paper.maker.bps", "1.0"],
            ["paper.taker.bps", "5.0"],
            ["paper.funding.included", "yes"],
            ["paper.borrow.included",  "n/a (spot)"],
            ["live.maker.bps", "— (mirror tier-1)"],
            ["live.taker.bps", "— (mirror tier-1)"],
          ]} />
        </Panel>
      </div>
    </div>
  );
}

window.LiveReadinessPage = LiveReadinessPage;
window.ConfigAdminPage = ConfigAdminPage;
window.StrategyAdminPage = StrategyAdminPage;
window.TrainerAdminPage = TrainerAdminPage;
window.OrchestratorAdminPage = OrchestratorAdminPage;
window.ExecutionAdminPage = ExecutionAdminPage;
===== END FILE: pages-admin.jsx =====

