// Static data + small helpers for the AI BOT V2 mockup.
// All numbers are illustrative; system is in PAPER mode, LIVE BLOCKED.

const NAV = [
  {
    section: "Operate",
    items: [
      { id: "mission-control",       label: "Mission Control",     status: "ok"    },
      { id: "signals",               label: "Signals",             status: "ok",   count: 47 },
      { id: "executions",            label: "Executions",          status: "ok"    },
      { id: "positions",             label: "Positions",           status: "ok",   count: 6 },
      { id: "symbols",               label: "Symbols",             status: "ok"    },
      { id: "paper-trading",         label: "Paper Trading",       status: "paper" },
      { id: "replay",                label: "Replay",              status: "dim"   },
    ],
  },
  {
    section: "Inspect",
    items: [
      { id: "signal-explainability", label: "Signal Explainability", status: "ok"   },
      { id: "trainer-monitor",       label: "Trainer Monitor",       status: "warn", count: 2 },
      { id: "coverage-atlas",        label: "Coverage / Atlas",      status: "ok"   },
      { id: "script-registry",       label: "Script Registry",       status: "warn", count: 11 },
      { id: "monitor-center",        label: "Monitor Center",        status: "ok"   },
      { id: "audit-ledger",          label: "Audit Ledger",          status: "ok"   },
    ],
  },
  {
    section: "Admin",
    items: [
      { id: "risk-control",          label: "Risk Control",          status: "block" },
      { id: "live-readiness",        label: "Live Readiness",        status: "block" },
      { id: "config-admin",          label: "Config Admin",          status: "ok"    },
      { id: "strategy-admin",        label: "Strategy Admin",        status: "ok"    },
      { id: "trainer-admin",         label: "Trainer Admin",         status: "ok"    },
      { id: "orchestrator-admin",    label: "Orchestrator Admin",    status: "ok"    },
      { id: "execution-admin",       label: "Execution Admin",       status: "ok"    },
    ],
  },
  {
    section: "AI Layer",
    items: [
      { id: "claude-admin",          label: "Claude Admin",          status: "ok"   },
      { id: "ollama",                label: "Ollama Local",          status: "ok"   },
      { id: "codex",                 label: "Codex Review",          status: "warn", count: 3 },
    ],
  },
  {
    section: "System",
    items: [
      { id: "system-health",         label: "System Health",         status: "ok"  },
      { id: "build-validation",      label: "Build / Validation",    status: "warn", count: 4 },
      { id: "mobile-readiness",      label: "Mobile Readiness",      status: "dim" },
    ],
  },
];

const SUBSYSTEMS = [
  { id: "trainer",      label: "Trainer",       status: "ok",    metric: "loss 0.0382",     detail: "step 184,201 · ckpt 0291",       last: "00:00:01.4" },
  { id: "orchestrator", label: "Orchestrator",  status: "ok",    metric: "throughput 9.4/s", detail: "queue 0 · 0 stuck",              last: "00:00:00.7" },
  { id: "risk-gateway", label: "Risk Gateway",  status: "block", metric: "live: BLOCKED",   detail: "12 rules armed · 0 overrides",   last: "00:00:00.3" },
  { id: "execution",   label: "Execution",      status: "paper", metric: "PAPER · 0 live",  detail: "adapter: replay-v2",             last: "00:00:01.1" },
  { id: "redis",        label: "Redis (v2)",   status: "ok",    metric: "ns aibotv2:*",     detail: "keys 12,481 · evicted 0",        last: "00:00:00.2" },
  { id: "postgres",     label: "Postgres",     status: "ok",    metric: "lag 0ms",         detail: "audit chain ok · 24h rows 1.2M", last: "00:00:00.8" },
];

const RISK_RULES = [
  { id: "live-trading",        label: "live trading enabled",        verdict: "BLOCKED",  reason: "operator approval required",                   level: "high"   },
  { id: "missing-attribution", label: "missing attribution",         verdict: "ARMED",    reason: "all signals must carry model_id + version",     level: "med"   },
  { id: "missing-signal-id",   label: "missing signal_id",           verdict: "ARMED",    reason: "uuidv7 required",                                level: "med"   },
  { id: "missing-confidence",  label: "missing confidence",          verdict: "ARMED",    reason: "calibrated [0..1] required",                     level: "med"   },
  { id: "stale-risk-add",      label: "stale risk-add signal",        verdict: "ARMED",    reason: "tick age > 2.5s rejects",                        level: "med"   },
  { id: "cross-margin",        label: "CROSS margin in live",         verdict: "BLOCKED",  reason: "ISOLATED only until live readiness review",      level: "high"  },
  { id: "leverage-cap",        label: "leverage above cap",           verdict: "ARMED",    reason: "cap 3x (paper) / 1x (live)",                     level: "med"   },
  { id: "duplicate-order-id",  label: "duplicate exchange_order_id",  verdict: "ARMED",    reason: "dedup window 24h",                               level: "med"   },
  { id: "missing-stop",        label: "missing stop policy",          verdict: "ARMED",    reason: "every signal must declare stop class",           level: "high"  },
  { id: "kill-switch-off",     label: "kill switch disabled",         verdict: "BLOCKED",  reason: "kill switch may not be disabled by automation",  level: "high"  },
  { id: "adjust-leverage",     label: "ADJUST_LEVERAGE",              verdict: "BLOCKED",  reason: "explicit human flag required",                   level: "high"  },
  { id: "hedge-dca",           label: "hedge / DCA enabled",          verdict: "ARMED",    reason: "deferred to strategy admin",                     level: "med"   },
];

const SIGNALS = [
  { id: "01HW9F2Z", t: "13:42:11.804", sym: "BTC-USDT", side: "LONG",  model: "hybrid-v4.2-ckpt0291", conf: 0.812, feat: "fresh 0.41s", stop: "ATR-2.4",  verdict: "ALLOW",  pnl: "+0.34%" },
  { id: "01HW9F2P", t: "13:42:09.181", sym: "ETH-USDT", side: "SHORT", model: "hybrid-v4.2-ckpt0291", conf: 0.704, feat: "fresh 0.62s", stop: "ATR-2.0",  verdict: "ALLOW",  pnl: "+0.11%" },
  { id: "01HW9F2D", t: "13:42:04.022", sym: "SOL-USDT", side: "LONG",  model: "hybrid-v4.2-ckpt0291", conf: 0.591, feat: "stale 3.1s",  stop: "ATR-2.6",  verdict: "BLOCK",  pnl: "—"      },
  { id: "01HW9F1Y", t: "13:42:01.475", sym: "AVAX-USDT",side: "LONG",  model: "hybrid-v4.2-ckpt0291", conf: 0.838, feat: "fresh 0.39s", stop: "ATR-2.2",  verdict: "ALLOW",  pnl: "+0.62%" },
  { id: "01HW9F1J", t: "13:41:58.901", sym: "BNB-USDT", side: "SHORT", model: "hybrid-v4.2-ckpt0291", conf: 0.523, feat: "fresh 0.51s", stop: "—",         verdict: "BLOCK",  pnl: "—"      },
  { id: "01HW9F18", t: "13:41:55.221", sym: "MATIC-USDT",side:"LONG",  model: "hybrid-v4.2-ckpt0291", conf: 0.776, feat: "fresh 0.44s", stop: "ATR-2.0",  verdict: "ALLOW",  pnl: "-0.08%" },
  { id: "01HW9F0V", t: "13:41:50.012", sym: "ARB-USDT", side: "LONG",  model: "hybrid-v4.2-ckpt0291", conf: 0.660, feat: "fresh 0.71s", stop: "ATR-2.6",  verdict: "ALLOW",  pnl: "+0.24%" },
  { id: "01HW9F0E", t: "13:41:45.811", sym: "DOGE-USDT",side: "SHORT", model: "hybrid-v4.2-ckpt0291", conf: 0.741, feat: "fresh 0.55s", stop: "ATR-1.8",  verdict: "ALLOW",  pnl: "+0.19%" },
];

const POSITIONS = [
  { sym: "BTC-USDT",  side: "L", qty: "0.0420",  entry: "60,418.10", mark: "60,612.45", upnl: "+8.16",  upnlPct: "+0.32%", age: "11m"   },
  { sym: "ETH-USDT",  side: "S", qty: "0.6100",  entry: "2,944.20",  mark: "2,935.81",  upnl: "+5.12",  upnlPct: "+0.28%", age: "07m"   },
  { sym: "AVAX-USDT", side: "L", qty: "12.000",  entry: "29.81",     mark: "30.02",     upnl: "+2.52",  upnlPct: "+0.70%", age: "04m"   },
  { sym: "SOL-USDT",  side: "L", qty: "1.4400",  entry: "138.92",    mark: "138.41",    upnl: "-0.73",  upnlPct: "-0.36%", age: "19m"   },
  { sym: "MATIC-USDT",side: "L", qty: "210.00",  entry: "0.6841",    mark: "0.6829",    upnl: "-0.25",  upnlPct: "-0.17%", age: "02m"   },
  { sym: "ARB-USDT",  side: "L", qty: "180.00",  entry: "0.9120",    mark: "0.9142",    upnl: "+0.40",  upnlPct: "+0.24%", age: "01m"   },
];

const AUDIT = [
  { seq: "1,204,481", t: "13:42:11.804", actor: "orchestrator", action: "signal.publish",        target: "01HW9F2Z", prev: "f2c4…91ae", curr: "a017…23dd", verdict: "ok" },
  { seq: "1,204,480", t: "13:42:11.804", actor: "risk-gateway", action: "gate.allow",            target: "01HW9F2Z", prev: "b8d1…77c0", curr: "f2c4…91ae", verdict: "ok" },
  { seq: "1,204,479", t: "13:42:11.802", actor: "trainer",      action: "prediction.publish",    target: "BTC-USDT", prev: "44ee…ae21", curr: "b8d1…77c0", verdict: "ok" },
  { seq: "1,204,478", t: "13:42:09.181", actor: "risk-gateway", action: "gate.allow",            target: "01HW9F2P", prev: "31ba…b7c4", curr: "44ee…ae21", verdict: "ok" },
  { seq: "1,204,477", t: "13:42:04.022", actor: "risk-gateway", action: "gate.block",            target: "01HW9F2D", prev: "00aa…1e7f", curr: "31ba…b7c4", verdict: "block" },
  { seq: "1,204,476", t: "13:42:01.475", actor: "execution",   action: "paper.fill",            target: "01HW9F1Y", prev: "9d72…5b8a", curr: "00aa…1e7f", verdict: "ok" },
  { seq: "1,204,475", t: "13:41:58.901", actor: "risk-gateway", action: "gate.block",            target: "01HW9F1J", prev: "5cef…83b1", curr: "9d72…5b8a", verdict: "block" },
  { seq: "1,204,474", t: "13:41:50.220", actor: "operator",     action: "config.update",         target: "leverage_cap_paper=3x", prev: "1100…aaff", curr: "5cef…83b1", verdict: "ok" },
];

const BUILD = [
  { id: "B-001", label: "scaffold.validation",       status: "PASS",  detail: "B_SCAFFOLD_VALIDATION.md verified · 14:02"  },
  { id: "B-002", label: "trainer.atlas.coverage",     status: "PASS",  detail: "Tier A: 31/31 sections raw-reviewed"        },
  { id: "B-003", label: "redis.namespace.isolation",  status: "PASS",  detail: "aibotv2:* only · 0 legacy writes detected" },
  { id: "B-004", label: "risk.gate.contract",        status: "WARN",  detail: "ADJUST_LEVERAGE path lacks raw evidence"   },
  { id: "B-005", label: "audit.chain.integrity",      status: "PASS",  detail: "1,204,481 links · 0 breaks"                 },
  { id: "B-006", label: "ollama.summary.verify",      status: "WARN",  detail: "3 packets pending Claude verification"      },
  { id: "B-007", label: "codex.review.gates",        status: "WARN",  detail: "milestone C review queued"                  },
  { id: "B-008", label: "live.readiness.checklist",  status: "WARN",  detail: "9 of 14 items unverified — see Live Ready." },
];

const TRAINER_PRED = [
  { sym: "BTC-USDT",  acc: 0.612, mae: 0.0021, brier: 0.184, drift: 0.04, last: "0.4s" },
  { sym: "ETH-USDT",  acc: 0.589, mae: 0.0030, brier: 0.198, drift: 0.07, last: "0.6s" },
  { sym: "SOL-USDT",  acc: 0.554, mae: 0.0048, brier: 0.214, drift: 0.18, last: "3.1s" },
  { sym: "AVAX-USDT", acc: 0.601, mae: 0.0034, brier: 0.191, drift: 0.05, last: "0.4s" },
  { sym: "BNB-USDT",  acc: 0.572, mae: 0.0029, brier: 0.205, drift: 0.09, last: "0.5s" },
  { sym: "MATIC-USDT",acc: 0.566, mae: 0.0041, brier: 0.211, drift: 0.11, last: "0.5s" },
];

// Equity curve seed (deterministic-ish ramp).
function makeEquityPath(width, height, points = 64) {
  // Start at 100k, end ~104.1k with realistic noise
  let v = 100000;
  const ys = [];
  const rng = (s => () => (s = (s * 9301 + 49297) % 233280) / 233280)(7);
  for (let i = 0; i < points; i++) {
    const drift = 65;            // slight up drift
    const noise = (rng() - 0.45) * 320;
    v += drift + noise;
    ys.push(v);
  }
  const min = Math.min(...ys), max = Math.max(...ys);
  const xs = ys.map((_, i) => (i / (points - 1)) * width);
  const yps = ys.map(y => height - ((y - min) / (max - min)) * height);
  const d  = xs.map((x, i) => `${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${yps[i].toFixed(2)}`).join(" ");
  const da = `${d} L ${width} ${height} L 0 ${height} Z`;
  return { d, da, min, max, last: ys[ys.length - 1], first: ys[0], ys };
}

// Tiny sparkline path
function makeSpark(seed, width = 64, height = 18, points = 24) {
  const rng = (s => () => (s = (s * 9301 + 49297) % 233280) / 233280)(seed);
  const ys = Array.from({ length: points }, () => rng());
  const min = Math.min(...ys), max = Math.max(...ys);
  const d = ys.map((y, i) => {
    const x = (i / (points - 1)) * width;
    const yy = height - ((y - min) / (max - min || 1)) * height;
    return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${yy.toFixed(2)}`;
  }).join(" ");
  return d;
}

window.AIBOT = {
  NAV, SUBSYSTEMS, RISK_RULES, SIGNALS, POSITIONS, AUDIT, BUILD, TRAINER_PRED,
  makeEquityPath, makeSpark,
};
===== END FILE: data.jsx =====

