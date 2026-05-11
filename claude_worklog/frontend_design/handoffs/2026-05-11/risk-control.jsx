// Risk Control — gate rules, dangerous controls, kill switch.

const { RISK_RULES } = window.AIBOT;

function RiskControl() {
  const [killArmed, setKillArmed] = React.useState(true);
  return (
    <div data-screen-label="11 Risk Control">
      <div className="panel bracketed hatch" style={{ padding: "18px 22px", marginBottom: 16 }}>
        <span className="br-bl" /><span className="br-br" />
        <Eyebrow>// risk control · dangerous surface · 2-operator approval enforced</Eyebrow>
        <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginTop: 8 }}>
          <h1 className="cond" style={{ fontSize: 30 }}>RISK CONTROL</h1>
          <Chip kind="block">LIVE TRADING · BLOCKED</Chip>
          <Chip>policy rev 18 · sha c7e2…b1</Chip>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 320px", gap: 16 }}>
        <Panel title="// gate rules · 12 armed">
          <table className="data">
            <thead>
              <tr><th>rule</th><th>verdict</th><th>level</th><th>reason</th><th style={{ textAlign: "right" }}>action</th></tr>
            </thead>
            <tbody>
              {RISK_RULES.map(r => (
                <tr key={r.id} className="row-hover">
                  <td className="mono" style={{ color: "var(--text)" }}>{r.label}</td>
                  <td>
                    <Chip kind={r.verdict === "BLOCKED" ? "block" : "ok"}>
                      {r.verdict}
                    </Chip>
                  </td>
                  <td className="mono" style={{ fontSize: 11, color: r.level === "high" ? "var(--block)" : "var(--text-mid)" }}>
                    {r.level.toUpperCase()}
                  </td>
                  <td className="mono" style={{ color: "var(--text-dim)", fontSize: 11 }}>{r.reason}</td>
                  <td style={{ textAlign: "right" }}>
                    <button className="btn" disabled={r.level === "high"}>edit</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <div style={{ display: "grid", gap: 16, alignContent: "start" }}>
          <Panel title="// kill switch" bracketed>
            <div className="hatch" style={{ padding: "16px 14px", border: "1px solid var(--border)", textAlign: "center" }}>
              <Eyebrow>status</Eyebrow>
              <div className="cond" style={{ fontSize: 34, marginTop: 4, color: killArmed ? "var(--accent)" : "var(--block)" }}>
                {killArmed ? "ARMED" : "TRIPPED"}
              </div>
              <div className="mono" style={{ fontSize: 11, color: "var(--text-dim)", marginTop: 4 }}>
                trip-latency 0.2s · cooldown 5m
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 14, justifyContent: "center" }}>
                <button className="btn danger" onClick={() => setKillArmed(false)}>TRIP NOW</button>
                <button className="btn" onClick={() => setKillArmed(true)}>RE-ARM</button>
              </div>
            </div>
            <div className="mono" style={{ fontSize: 10.5, color: "var(--text-dim)", marginTop: 12 }}>
              trip cancels open orders · halts orchestrator · sets execution to read-only · audit-logged.
            </div>
          </Panel>

          <Panel title="// dangerous controls">
            {[
              { k: "enable live trading",  v: "BLOCKED" },
              { k: "add live api keys",     v: "BLOCKED" },
              { k: "increase leverage",     v: "BLOCKED" },
              { k: "enable CROSS margin",  v: "BLOCKED" },
              { k: "increase position cap", v: "BLOCKED" },
              { k: "disable kill switch",  v: "BLOCKED" },
              { k: "ADJUST_LEVERAGE flag", v: "BLOCKED" },
              { k: "enable hedge / DCA",   v: "ARMED"  },
              { k: "switch paper→live",   v: "BLOCKED" },
            ].map(d => (
              <div key={d.k} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: "1px solid var(--border)", alignItems: "center" }}>
                <span className="mono" style={{ fontSize: 11.5, color: "var(--text)" }}>{d.k}</span>
                <Chip kind={d.v === "BLOCKED" ? "block" : "warn"}>{d.v}</Chip>
              </div>
            ))}
            <div className="mono" style={{ fontSize: 10.5, color: "var(--text-dim)", marginTop: 10, lineHeight: 1.5 }}>
              every action here is dual-approved · ledger-pinned · cooldown 60s after escalation.
            </div>
          </Panel>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// live readiness · 9 of 14 unverified">
          {[
            { k: "risk.gate.contract.raw-evidenced",     ok: true,  n: "src lines L142-L188 · audit row 1,204,402" },
            { k: "audit.chain.integrity.verified",        ok: true,  n: "1,204,481 links · 0 breaks" },
            { k: "redis.namespace.isolation.proven",      ok: true,  n: "aibotv2:* only · 0 legacy writes" },
            { k: "trainer.atlas.tier-A.complete",         ok: true,  n: "31/31 sections raw-reviewed" },
            { k: "kill.switch.physical-or-logical.tested", ok: true, n: "last drill 2026-05-08 13:02" },
            { k: "ADJUST_LEVERAGE.evidence.complete",     ok: false, n: "no raw exchange-action trace" },
            { k: "codex.review.milestone-C.signed-off",   ok: false, n: "queued · 3 review gates open" },
            { k: "operator.2-of-N.policy.bound",          ok: false, n: "policy defined · key ceremony pending" },
            { k: "live.api.keys.escrowed",               ok: false, n: "not configured · expected" },
            { k: "live.dry-run.drill",                     ok: false, n: "not scheduled" },
          ].map(r => (
            <div key={r.k} style={{ display: "grid", gridTemplateColumns: "10px 1fr auto", gap: 10, alignItems: "center", padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
              <StatusDot status={r.ok ? "ok" : "warn"} />
              <div>
                <div className="mono" style={{ fontSize: 11.5, color: "var(--text)" }}>{r.k}</div>
                <div className="mono" style={{ fontSize: 10.5, color: "var(--text-dim)" }}>{r.n}</div>
              </div>
              <Chip kind={r.ok ? "ok" : "warn"}>{r.ok ? "VERIFIED" : "PENDING"}</Chip>
            </div>
          ))}
        </Panel>

        <Panel title="// approval queue">
          {[
            { id: "AP-211", t: "enable hedge mode on BTC-USDT", req: "strategy-admin", needs: "2 / 2", got: "1 / 2", state: "AWAIT-2ND" },
            { id: "AP-210", t: "lift leverage cap to 3.5x (paper)", req: "operator", needs: "2 / 2", got: "0 / 2", state: "AWAIT-1ST" },
            { id: "AP-209", t: "rotate ollama model to llama3.1:8b", req: "ai-admin",  needs: "1 / 1", got: "1 / 1", state: "EXECUTING" },
            { id: "AP-208", t: "promote ckpt 0291 → 0292",          req: "trainer-admin", needs: "1 / 1", got: "0 / 1", state: "AWAIT-1ST" },
            { id: "AP-207", t: "purge stale signals > 48h",          req: "audit-admin", needs: "1 / 1", got: "1 / 1", state: "DONE" },
          ].map(a => (
            <div key={a.id} style={{ display: "grid", gridTemplateColumns: "60px 1fr 90px 90px", gap: 10, padding: "8px 0", borderBottom: "1px solid var(--border)", alignItems: "center" }}>
              <span className="mono" style={{ fontSize: 10, color: "var(--text-dim)" }}>{a.id}</span>
              <div>
                <div className="mono" style={{ fontSize: 12, color: "var(--text)" }}>{a.t}</div>
                <div className="mono" style={{ fontSize: 10.5, color: "var(--text-dim)", marginTop: 2 }}>req · {a.req} · approvals {a.got} of {a.needs}</div>
              </div>
              <span className="mono" style={{ fontSize: 10.5, color: "var(--text-mid)" }}>{a.state}</span>
              <span style={{ textAlign: "right" }}>
                <button className="btn" disabled={a.state === "DONE"}>review</button>
              </span>
            </div>
          ))}
        </Panel>
      </div>
    </div>
  );
}

window.RiskControl = RiskControl;
===== END FILE: risk-control.jsx =====

