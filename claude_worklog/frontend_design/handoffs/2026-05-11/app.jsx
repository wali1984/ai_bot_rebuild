// Top-level app shell: sidebar nav + top bar + page router.

const { NAV } = window.AIBOT;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "dark"
}/*EDITMODE-END*/;

function App() {
  const [page, setPage] = React.useState("mission-control");
  const [tweaks, setTweak] = window.useTweaks
    ? window.useTweaks(TWEAK_DEFAULTS)
    : [TWEAK_DEFAULTS, () => {}];
  const theme = tweaks.theme || "dark";

  React.useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const pageLabel = React.useMemo(() => {
    for (const sec of NAV) for (const it of sec.items) if (it.id === page) return it.label;
    return "Module";
  }, [page]);

  const Body = (() => {
    const w = window;
    if (page === "mission-control")       return <MissionControl />;
    if (page === "signal-explainability") return <SignalExplainability />;
    if (page === "risk-control")          return <RiskControl />;
    if (page === "signals"            && w.SignalsPage)            return <w.SignalsPage />;
    if (page === "executions"         && w.ExecutionsPage)         return <w.ExecutionsPage />;
    if (page === "positions"          && w.PositionsPage)          return <w.PositionsPage />;
    if (page === "symbols"            && w.SymbolsPage)            return <w.SymbolsPage />;
    if (page === "paper-trading"      && w.PaperTradingPage)       return <w.PaperTradingPage />;
    if (page === "replay"             && w.ReplayPage)             return <w.ReplayPage />;
    if (page === "trainer-monitor"    && w.TrainerMonitorPage)     return <w.TrainerMonitorPage />;
    if (page === "coverage-atlas"     && w.CoverageAtlasPage)      return <w.CoverageAtlasPage />;
    if (page === "script-registry"    && w.ScriptRegistryPage)     return <w.ScriptRegistryPage />;
    if (page === "monitor-center"     && w.MonitorCenterPage)      return <w.MonitorCenterPage />;
    if (page === "audit-ledger"       && w.AuditLedgerPage)        return <w.AuditLedgerPage />;
    if (page === "live-readiness"     && w.LiveReadinessPage)      return <w.LiveReadinessPage />;
    if (page === "config-admin"       && w.ConfigAdminPage)        return <w.ConfigAdminPage />;
    if (page === "strategy-admin"     && w.StrategyAdminPage)      return <w.StrategyAdminPage />;
    if (page === "trainer-admin"      && w.TrainerAdminPage)       return <w.TrainerAdminPage />;
    if (page === "orchestrator-admin" && w.OrchestratorAdminPage)  return <w.OrchestratorAdminPage />;
    if (page === "execution-admin"    && w.ExecutionAdminPage)     return <w.ExecutionAdminPage />;
    if (page === "claude-admin"       && w.ClaudeAdminPage)        return <w.ClaudeAdminPage />;
    if (page === "ollama"             && w.OllamaPage)             return <w.OllamaPage />;
    if (page === "codex"              && w.CodexPage)              return <w.CodexPage />;
    if (page === "system-health"      && w.SystemHealthPage)       return <w.SystemHealthPage />;
    if (page === "build-validation"   && w.BuildValidationPage)    return <w.BuildValidationPage />;
    if (page === "mobile-readiness"   && w.MobileReadinessPage)    return <w.MobileReadinessPage />;
    return <ModulePlaceholder id={page} label={pageLabel} />;
  })();

  return (
    <div className="app">
      <BlockedStrip />
      <Sidebar page={page} setPage={setPage} />
      <TopBar pageLabel={pageLabel} />
      <main className="grid-bg" style={{ gridColumn: "2", padding: 18, minWidth: 0 }}>
        {Body}
      </main>
      {window.TweaksPanel && (
        <window.TweaksPanel title="Tweaks">
          <window.TweakSection title="Theme">
            <window.TweakRadio
              label="Mode"
              value={theme}
              onChange={v => setTweak("theme", v)}
              options={[
                { label: "Dark", value: "dark" },
                { label: "Light", value: "light" },
                { label: "Term.", value: "terminal" },
              ]}
            />
          </window.TweakSection>
        </window.TweaksPanel>
      )}
    </div>
  );
}

function BlockedStrip() {
  const msgs = [
    "LIVE TRADING · BLOCKED",
    "policy rev 18",
    "9 / 14 live-readiness items pending",
    "kill switch · ARMED",
    "operator approval required for any dangerous control",
    "audit chain · 1,204,481 links · 0 breaks",
    "redis ns · aibotv2:*",
    "paper mode · replay adapter v2",
  ];
  const run = (<span style={{ display: "inline-flex", gap: 36 }}>
    {msgs.concat(msgs).map((m, i) => (
      <span key={i} className="mono" style={{ fontSize: 10.5, letterSpacing: "0.10em", textTransform: "uppercase", color: "var(--accent)" }}>
        <span style={{ color: "var(--block)", marginRight: 8 }}>■</span>{m}
      </span>
    ))}
  </span>);
  return (
    <div className="blocked-strip">
      <div className="blocked-strip-inner">
        <div className="blocked-marquee">{run}</div>
      </div>
    </div>
  );
}

function Sidebar({ page, setPage }) {
  return (
    <aside style={{
      gridColumn: "1", gridRow: "2 / span 2",
      background: "var(--surface)",
      borderRight: "1px solid var(--border)",
      padding: "14px 0 18px",
      position: "sticky", top: 0, alignSelf: "start",
      height: "calc(100vh - 26px)",
      overflowY: "auto",
    }}>
      <div style={{ padding: "0 16px 14px", display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{
          width: 22, height: 22, border: "1px solid var(--accent)",
          display: "grid", placeItems: "center",
          fontFamily: "IBM Plex Mono, monospace", fontSize: 11, color: "var(--accent)",
        }}>◢</div>
        <div>
          <div className="cond" style={{ fontSize: 14, letterSpacing: "0.04em", lineHeight: 1 }}>AI BOT · V2</div>
          <div className="mono" style={{ fontSize: 9, color: "var(--text-dim)", letterSpacing: "0.10em", marginTop: 3 }}>CONTROL PLANE · 0.0.1</div>
        </div>
      </div>
      <div className="hr" />

      {NAV.map(sec => (
        <div key={sec.section} style={{ padding: "10px 0 6px" }}>
          <div className="label-mono" style={{ padding: "4px 16px 6px", color: "var(--text-faint)" }}>
            // {sec.section}
          </div>
          {sec.items.map(it => {
            const active = page === it.id;
            return (
              <button
                key={it.id}
                onClick={() => setPage(it.id)}
                style={{
                  display: "flex", alignItems: "center", gap: 9,
                  width: "100%",
                  padding: "5px 14px 5px 16px",
                  textAlign: "left",
                  borderLeft: `2px solid ${active ? "var(--accent)" : "transparent"}`,
                  background: active ? "color-mix(in oklch, var(--accent) 6%, transparent)" : "transparent",
                  color: active ? "var(--text)" : "var(--text-mid)",
                  fontSize: 12.5,
                  lineHeight: 1.3,
                  transition: "background .12s, color .12s",
                }}
              >
                <StatusDot status={it.status === "dim" ? "" : it.status} />
                <span style={{ flex: 1 }}>{it.label}</span>
                {it.count && (
                  <span className="mono" style={{
                    fontSize: 10, color: it.status === "warn" ? "var(--accent)" : it.status === "block" ? "var(--block)" : "var(--text-dim)",
                    minWidth: 18, textAlign: "right",
                  }}>{it.count}</span>
                )}
              </button>
            );
          })}
        </div>
      ))}

      <div className="hr" style={{ margin: "8px 0" }} />
      <div style={{ padding: "0 16px", display: "grid", gap: 6 }}>
        <div className="mono" style={{ fontSize: 10, color: "var(--text-dim)", display: "flex", justifyContent: "space-between" }}>
          <span>redis</span><span style={{ color: "var(--ok)" }}>● ok</span>
        </div>
        <div className="mono" style={{ fontSize: 10, color: "var(--text-dim)", display: "flex", justifyContent: "space-between" }}>
          <span>postgres</span><span style={{ color: "var(--ok)" }}>● ok</span>
        </div>
        <div className="mono" style={{ fontSize: 10, color: "var(--text-dim)", display: "flex", justifyContent: "space-between" }}>
          <span>trainer ipc</span><span style={{ color: "var(--ok)" }}>● ok</span>
        </div>
        <div className="mono" style={{ fontSize: 10, color: "var(--text-dim)", display: "flex", justifyContent: "space-between" }}>
          <span>live api</span><span style={{ color: "var(--block)" }}>● blocked</span>
        </div>
      </div>
    </aside>
  );
}

function TopBar({ pageLabel }) {
  const clock = useClock();
  const tick = useTicker(1000);
  const latency = 0.42 + ((tick * 13) % 17) / 100;
  return (
    <header style={{
      gridColumn: "2", gridRow: "2",
      display: "flex", alignItems: "center", gap: 14,
      padding: "10px 18px",
      borderBottom: "1px solid var(--border)",
      background: "var(--surface)",
      position: "sticky", top: 0, zIndex: 5,
    }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <span className="label-mono" style={{ color: "var(--text-faint)" }}>//</span>
        <span className="cond" style={{ fontSize: 17, letterSpacing: "0.02em" }}>{pageLabel}</span>
      </div>

      <div style={{ flex: 1 }} />

      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <Telemetry label="orch latency" value={`${latency.toFixed(2)}ms`} tone="ok" />
        <Telemetry label="gate latency" value="0.84ms" tone="ok" />
        <Telemetry label="redis ops/s" value={`${(9.4 + (tick % 5) * 0.1).toFixed(1)}`} tone="ok" />
        <span style={{ height: 16, width: 1, background: "var(--border)" }} />
        <Chip kind="paper">MODE · PAPER</Chip>
        <Chip kind="block">LIVE · BLOCKED</Chip>
        <span style={{ height: 16, width: 1, background: "var(--border)" }} />
        <div className="mono" style={{ fontSize: 11, color: "var(--text-mid)", textAlign: "right" }}>
          <div>{fmtClock(clock)}</div>
          <div style={{ color: "var(--text-dim)", fontSize: 10 }}>{fmtDate(clock)} · op wali1984</div>
        </div>
      </div>
    </header>
  );
}

function Telemetry({ label, value, tone }) {
  const c = tone === "ok" ? "var(--ok)" : tone === "warn" ? "var(--accent)" : tone === "block" ? "var(--block)" : "var(--text)";
  return (
    <div className="mono" style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span style={{ fontSize: 10, color: "var(--text-dim)", letterSpacing: "0.08em", textTransform: "uppercase" }}>{label}</span>
      <span style={{ fontSize: 12, color: c, fontVariantNumeric: "tabular-nums" }}>{value}</span>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
===== END FILE: app.jsx =====

