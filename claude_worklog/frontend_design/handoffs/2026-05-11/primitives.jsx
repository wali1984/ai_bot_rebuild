// Shared small primitives.

const { useEffect, useState, useRef, useMemo } = React;

function StatusDot({ status = "ok", pulse = false, size = 6 }) {
  const cls = `dot ${status}` + (pulse ? " pulse" : "");
  return <span className={cls} style={{ width: size, height: size }} />;
}

function Chip({ children, kind, style }) {
  const cls = "chip" + (kind ? ` solid-${kind}` : "");
  return <span className={cls} style={style}>{children}</span>;
}

function Panel({ title, right, children, bracketed = false, style, bodyStyle, noPad = false }) {
  return (
    <div className={"panel" + (bracketed ? " bracketed" : "")} style={style}>
      {bracketed && <><span className="br-bl" /><span className="br-br" /></>}
      {title && (
        <div className="panel-head">
          <div className="panel-title">{title}</div>
          {right}
        </div>
      )}
      <div className="panel-body" style={{ padding: noPad ? 0 : undefined, ...(bodyStyle || {}) }}>
        {children}
      </div>
    </div>
  );
}

function Eyebrow({ children, style }) {
  return <div className="eyebrow" style={style}>{children}</div>;
}

// useClock — wall clock that ticks every second
function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

// useTicker — return a number that flips every `ms` ms, with seed
function useTicker(ms = 1500) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), ms);
    return () => clearInterval(id);
  }, [ms]);
  return tick;
}

function fmtClock(d) {
  const pad = n => String(n).padStart(2, "0");
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC`;
}

function fmtDate(d) {
  const pad = n => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())}`;
}

Object.assign(window, { StatusDot, Chip, Panel, Eyebrow, useClock, useTicker, fmtClock, fmtDate });
===== END FILE: primitives.jsx =====

