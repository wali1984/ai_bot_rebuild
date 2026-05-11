// AI Layer: Claude Admin, Ollama Local, Codex Review

function ClaudeAdminPage() {
  return (
    <div>
      <PageHeader screen="22 Claude Admin" sub="ai supervision · narration · verification · audit-pinned" title="CLAUDE ADMIN"
        chips={<><Chip kind="ok">CONNECTED · claude-sonnet-4.5</Chip><Chip>quota 14% / day</Chip><Chip kind="warn">3 verify pending</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12, marginBottom: 16 }}>
        {[
          { l: "calls · 24h",         v: "412",     t: "var(--text)" },
          { l: "tokens · in / out",   v: "1.4M / 218k", t: "var(--text)" },
          { l: "p99 latency",         v: "2.81s",   t: "var(--text)" },
          { l: "verification rate",   v: "98.2%",   t: "var(--ok)" },
        ].map(k => (
          <div key={k.l} className="panel" style={{ padding: "12px 14px" }}>
            <span className="label-mono">{k.l}</span>
            <div className="kpi-num" style={{ fontSize: 20, marginTop: 6, color: k.t }}>{k.v}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,2fr) minmax(0,1fr)", gap: 16 }}>
        <Panel title="// recent calls" bodyStyle={{ padding: 0 }}>
          <table className="data">
            <thead><tr><th>id</th><th>time</th><th>kind</th><th>target</th><th>tokens</th><th>verify</th><th>verdict</th></tr></thead>
            <tbody>
              {[
                ["C-04481", "13:41:11", "supervise.signal", "01HW9F2Z", "412 / 184", "auto", "ok"],
                ["C-04480", "13:38:41", "verify.ollama",    "OL-0114",  "812 / 41",  "—",    "ok"],
                ["C-04479", "13:33:11", "narrate.shift",    "shift-12", "1,021 / 311","auto", "ok"],
                ["C-04478", "13:28:01", "review.code.diff", "PR-118",   "2,418 / 612","operator","approved"],
                ["C-04477", "13:21:41", "supervise.gate",   "01HW9F2D", "318 / 92",  "auto", "block"],
                ["C-04476", "13:14:11", "verify.ollama",    "OL-0113",  "742 / 38",  "—",    "ok"],
                ["C-04475", "13:01:41", "narrate.audit",    "1,204,400","612 / 211", "auto", "ok"],
                ["C-04474", "12:48:21", "supervise.signal", "01HW9F1J", "384 / 178", "auto", "block"],
                ["C-04473", "12:42:11", "review.runbook",   "RB-021",   "1,841 / 612","operator","approved"],
                ["C-04472", "12:28:41", "verify.ollama",    "OL-0112",  "812 / 44",  "—",    "ok"],
                ["C-04471", "12:11:01", "supervise.shift",  "shift-11", "2,141 / 612","auto","ok"],
              ].map(r => (
                <tr key={r[0]} className="row-hover">
                  <td className="mono">{r[0]}</td>
                  <td className="mono" style={{ color: "var(--text-dim)" }}>{r[1]}</td>
                  <td className="mono" style={{ color: "var(--accent)" }}>{r[2]}</td>
                  <td className="mono">{r[3]}</td>
                  <td className="mono" style={{ fontSize: 11, color: "var(--text-mid)" }}>{r[4]}</td>
                  <td className="mono" style={{ color: "var(--text-mid)" }}>{r[5]}</td>
                  <td><Chip kind={r[6] === "ok" || r[6] === "approved" ? "ok" : "block"}>{r[6]}</Chip></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel title="// supervision settings">
          <KVTable rows={[
            ["model", "claude-sonnet-4.5"],
            ["fallback", "claude-haiku-4.5"],
            ["supervise.signals", "on (sample 10%)"],
            ["supervise.gates",   "on (all blocks)"],
            ["verify.ollama",     "on (all)"],
            ["narrate.shift",     "every 4h"],
            ["narrate.audit.window", "1k events"],
            ["temperature", "0.2"],
            ["max.output.tokens", "1024"],
            ["timeout.ms", "10,000"],
            ["pii.redaction", "on"],
            ["telemetry.pinned", "yes · audit"],
          ]} />
        </Panel>
      </div>

      <Panel title="// shift narration · last 4h window" style={{ marginTop: 16 }}>
        <div className="mono" style={{ fontSize: 12, color: "var(--text-mid)", lineHeight: 1.7 }}>
          <div style={{ color: "var(--text-dim)" }}># shift 13 · 10:00 → 14:00 UTC · narrated by claude-sonnet-4.5</div>
          <p style={{ margin: "10px 0" }}>
            paper session opened at $103,841; closed last bar at <span style={{ color: "var(--ok)" }}>$104,112 (+0.26%)</span> on 47 closed trades.
            primary driver: <span style={{ color: "var(--accent)" }}>mass-momentum-v3</span> on BTC + AVAX with 14 of 18 wins, mean R 0.81.
            one drift alert fired on SOL-USDT (KS 0.18 &gt; 0.15) at 12:48 — auto-pause armed but did not trip; model continues to publish with degraded confidence.
          </p>
          <p style={{ margin: "10px 0" }}>
            risk gateway blocked 4 of 27 signals in this window. blocks were textbook: 2 missing_stop_policy from regime-flip-v0 draft, 1 stale_feature (3.1s), 1 leverage_above_cap from a misconfigured paper subaccount (3.4x &gt; 3.0x).
          </p>
          <p style={{ margin: "10px 0", color: "var(--block)" }}>
            no live-trading attempts. live remains BLOCKED on 5 P0 readiness items.
          </p>
        </div>
      </Panel>
    </div>
  );
}

function OllamaPage() {
  return (
    <div>
      <PageHeader screen="23 Ollama Local" sub="local model · cheap summaries · cross-checked by claude" title="OLLAMA · LOCAL ASSISTANT"
        chips={<><Chip kind="ok">CONNECTED · llama3.1:8b-instruct-q5</Chip><Chip>local · 0 net egress</Chip><Chip kind="warn">3 unverified</Chip></>} />

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", gap: 12, marginBottom: 16 }}>
        {[
          { l: "calls · 24h",         v: "1,841",   t: "var(--text)" },
          { l: "p50 / p99 latency",   v: "0.21s / 1.4s",  t: "var(--text)" },
          { l: "verify success",      v: "98.2%",   t: "var(--ok)" },
          { l: "verify pending",      v: "3",       t: "var(--accent)" },
        ].map(k => (
          <div key={k.l} className="panel" style={{ padding: "12px 14px" }}>
            <span className="label-mono">{k.l}</span>
            <div className="kpi-num" style={{ fontSize: 20, marginTop: 6, color: k.t }}>{k.v}</div>
          </div>
        ))}
      </div>

      <Panel title="// packets · summaries written by ollama, cross-checked by claude" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>id</th><th>kind</th><th>target</th><th>tokens</th><th>latency</th><th>claude verdict</th><th>state</th></tr></thead>
          <tbody>
            {[
              ["OL-0118","feature.snapshot.summary","BTC-USDT @ 13:42:11","128 / 41","0.32s","ok","verified"],
              ["OL-0117","gate.block.summary","01HW9F2D","148 / 64","0.41s","ok","verified"],
              ["OL-0116","audit.window.summary","1,204,400 → 1,204,481","1,021 / 311","0.92s","ok","verified"],
              ["OL-0115","fill.summary","EX-284100","82 / 38","0.21s","ok","verified"],
              ["OL-0114","strategy.run.summary","RP-0118","812 / 411","0.84s","drift · 1 fact","pending"],
              ["OL-0113","strategy.run.summary","RP-0117","742 / 388","0.81s","ok","verified"],
              ["OL-0112","gate.block.summary","01HW9F1J","148 / 71","0.31s","drift · 2 facts","pending"],
              ["OL-0111","feature.drift.summary","SOL-USDT","384 / 144","0.51s","drift · 1 fact","pending"],
              ["OL-0110","narration.handoff","shift-12","2,141 / 612","1.21s","ok","verified"],
              ["OL-0109","signal.context","01HW9F0V","312 / 84","0.41s","ok","verified"],
            ].map(r => (
              <tr key={r[0]} className="row-hover">
                <td className="mono">{r[0]}</td>
                <td className="mono" style={{ color: "var(--accent)" }}>{r[1]}</td>
                <td className="mono">{r[2]}</td>
                <td className="mono" style={{ fontSize: 11, color: "var(--text-mid)" }}>{r[3]}</td>
                <td className="mono">{r[4]}</td>
                <td className="mono" style={{ color: r[5].includes("drift") ? "var(--accent)" : "var(--ok)", fontSize: 11 }}>{r[5]}</td>
                <td><Chip kind={r[6] === "verified" ? "ok" : "warn"}>{r[6]}</Chip></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// model + runtime">
          <KVTable rows={[
            ["model", "llama3.1:8b-instruct-q5_K_M"],
            ["host", "localhost:11434"],
            ["context.window", "8,192"],
            ["gpu", "rtx 4090 · 24gb · 41% util"],
            ["queue", "0 (max 32)"],
            ["concurrency", "4 workers"],
            ["timeout.ms", "5,000"],
            ["egress.policy", "none · local-only enforced"],
            ["temperature", "0.1"],
            ["top.p", "0.9"],
            ["verify.policy", "claude on all summaries"],
          ]} />
        </Panel>
        <Panel title="// verification drift causes · 24h">
          {[
            { r: "fact: number mismatch (rounded)", c: 7 },
            { r: "fact: missing risk-gate verdict", c: 3 },
            { r: "fact: wrong checkpoint id",        c: 2 },
            { r: "fact: hallucinated symbol",        c: 1 },
          ].map(x => (
            <div key={x.r} style={{ display: "grid", gridTemplateColumns: "1fr 40px", gap: 10, padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
              <span className="mono" style={{ fontSize: 11.5 }}>{x.r}</span>
              <span className="mono" style={{ textAlign: "right", color: "var(--accent)" }}>{x.c}</span>
            </div>
          ))}
        </Panel>
      </div>
    </div>
  );
}

function CodexPage() {
  return (
    <div>
      <PageHeader screen="24 Codex Review" sub="code review gates · milestone reviews · diff annotation" title="CODEX REVIEW"
        chips={<><Chip kind="warn">3 OPEN</Chip><Chip>milestone C</Chip><Chip kind="ok">14 SHIPPED 7d</Chip></>} />

      <Panel title="// open reviews" bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>id</th><th>title</th><th>scope</th><th>files</th><th>+ / −</th><th>findings</th><th>state</th><th></th></tr></thead>
          <tbody>
            {[
              ["CR-0118", "live.adapter.skeleton",          "execution",  "8",  "+412 / −18",  "P0: contract tests missing", "BLOCK"],
              ["CR-0117", "feature.freshness.budget.tune", "trainer",    "3",  "+44 / −12",   "P2: doc update needed",       "WARN"],
              ["CR-0116", "audit.witness.service.stub",   "audit",      "4",  "+118 / −0",  "P1: external witness not wired","WARN"],
            ].map(r => (
              <tr key={r[0]} className="row-hover">
                <td className="mono">{r[0]}</td>
                <td className="mono"><strong>{r[1]}</strong></td>
                <td className="mono" style={{ color: "var(--text-mid)" }}>{r[2]}</td>
                <td className="mono">{r[3]}</td>
                <td className="mono"><span style={{ color: "var(--ok)" }}>{r[4].split(" / ")[0]}</span> / <span style={{ color: "var(--block)" }}>{r[4].split(" / ")[1]}</span></td>
                <td className="mono" style={{ fontSize: 11, color: "var(--text-mid)" }}>{r[5]}</td>
                <td><Chip kind={r[6] === "BLOCK" ? "block" : "warn"}>{r[6]}</Chip></td>
                <td><button className="btn">open</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <Panel title="// recent ships · 7d" style={{ marginTop: 16 }} bodyStyle={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th>id</th><th>title</th><th>scope</th><th>shipped</th><th>review</th><th>follow-up</th></tr></thead>
          <tbody>
            {[
              ["CR-0115","trainer.calibration.refit","trainer","2026-05-09 12:48","approved · 2/2","none"],
              ["CR-0114","redis.namespace.migrate","platform","2026-05-08 21:12","approved · 2/2","monitor 30d"],
              ["CR-0113","gate.contract.unify","risk","2026-05-08 14:21","approved · 2/2","none"],
              ["CR-0112","paper.adapter.fee.mirror","execution","2026-05-07 11:01","approved · 2/2","none"],
              ["CR-0111","atlas.coverage.audit","platform","2026-05-06 18:42","approved · 2/2","tier B"],
              ["CR-0110","trainer.checkpoint.retain","trainer","2026-05-05 09:41","approved · 2/2","none"],
              ["CR-0109","monitor.kill.switch.cron","ops","2026-05-04 17:01","approved · 2/2","none"],
            ].map(r => (
              <tr key={r[0]} className="row-hover">
                {r.map((c,i) => <td key={i} className="mono" style={{ color: i === 4 ? "var(--ok)" : i === 3 ? "var(--text-dim)" : i === 5 ? "var(--text-mid)" : "var(--text)" }}>{c}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 16, marginTop: 16 }}>
        <Panel title="// review gates">
          <KVTable rows={[
            ["min approvers · code", "2 of 3"],
            ["min approvers · risk-policy", "3 of 3"],
            ["required reviewers · risk", "risk.admin"],
            ["required reviewers · execution", "exec.lead"],
            ["block.on.contract.tests", "yes"],
            ["block.on.audit.coverage.regression", "yes"],
            ["claude.review.opt-in", "all PRs · advisory"],
            ["sla.first.touch.hours", "4"],
            ["sla.merge.business-hours", "24"],
          ]} />
        </Panel>
        <Panel title="// claude advisory · queued">
          <div className="mono" style={{ fontSize: 12, lineHeight: 1.7, color: "var(--text-mid)" }}>
            <p style={{ margin: "0 0 8px" }}><span style={{ color: "var(--accent)" }}>CR-0118</span> — the new live adapter skeleton exposes <code>place_order</code> without a precondition that asserts <code>config.live.enabled == false → reject</code>. recommend a guard at adapter entry, not only at gateway, so the lock is defence-in-depth.</p>
            <p style={{ margin: "8px 0" }}><span style={{ color: "var(--accent)" }}>CR-0117</span> — tightening freshness from 2.5s → 2.0s will likely push burn-rate above 1.5x on SOL + DOGE during US open. recommend phased: 2.3s for 7d, observe, then 2.0s.</p>
            <p style={{ margin: "8px 0 0" }}><span style={{ color: "var(--accent)" }}>CR-0116</span> — audit witness stub should produce a verifiable receipt even when disabled (no-op record), so absence of evidence remains explicit.</p>
          </div>
        </Panel>
      </div>
    </div>
  );
}

window.ClaudeAdminPage = ClaudeAdminPage;
window.OllamaPage = OllamaPage;
window.CodexPage = CodexPage;
===== END FILE: pages-ai.jsx =====

