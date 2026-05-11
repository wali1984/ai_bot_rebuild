// Module placeholder — shown for nav items we haven't fully designed yet.

function ModulePlaceholder({ id, label }) {
  return (
    <div data-screen-label={`${id}`}>
      <div className="panel bracketed hatch" style={{ padding: "22px 24px", marginBottom: 16 }}>
        <span className="br-bl" /><span className="br-br" />
        <Eyebrow>// module · placeholder · not yet wired</Eyebrow>
        <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginTop: 8 }}>
          <h1 className="cond" style={{ fontSize: 30 }}>{label.toUpperCase()}</h1>
          <Chip>module · {id}</Chip>
        </div>
        <div className="mono" style={{ marginTop: 10, fontSize: 12, color: "var(--text-dim)" }}>
          This screen is part of the V2 page inventory — Mission Control, Signal Explainability, and Risk Control are the three fully-designed surfaces in this mockup.
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 16 }}>
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="panel" style={{ minHeight: 160, padding: 0, position: "relative", overflow: "hidden" }}>
            <div className="panel-head">
              <span className="panel-title">// slot · {String(i + 1).padStart(2, "0")}</span>
              <span className="label-mono" style={{ color: "var(--text-faint)" }}>placeholder</span>
            </div>
            <div className="hatch" style={{ height: 124, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <span className="mono" style={{ fontSize: 11, color: "var(--text-dim)" }}>
                {label} · panel {i + 1}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

window.ModulePlaceholder = ModulePlaceholder;
===== END FILE: module-placeholder.jsx =====

