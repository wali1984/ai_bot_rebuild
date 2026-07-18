/**
 * Shared chart palette + styling for NERVYX trader surfaces.
 *
 * Palette provenance (dataviz skill): the categorical slots are the skill's
 * reference dark-mode set (validated as a set — worst adjacent CVD ΔE 10.3, the
 * floor band, so ≥4 series always ship direct labels). Positive/negative use the
 * trading-domain green/red status pair and ALWAYS carry a +/- sign or label as the
 * secondary (non-colour) encoding, satisfying the relief rule. Sequential = one
 * hue (brand violet) light→dark. Text always wears text tokens, never a series hue.
 */

export const CHART = {
  // Trading status (diverging +/-) — semantic, paired with sign/label.
  pos: '#22c55e',
  neg: '#ef4444',
  neutral: '#f59e0b',
  // Brand + info accents (sequential / single-series).
  accent: '#7c5cff', // NERVYX violet
  info: '#3987e5',
  cyan: '#22d3ee',
  // Ink (text tokens — never used for marks).
  ink: 'var(--text-primary)',
  inkSoft: 'var(--text-secondary)',
  inkMuted: 'var(--text-muted)',
  grid: 'rgba(148,163,184,0.14)',
  surface: 'var(--bg-panel)',
} as const;

/** Validated dark-mode categorical order (fixed — assign in order, never cycle). */
export const CATEGORICAL: string[] = [
  '#3987e5', // blue
  '#199e70', // aqua
  '#c98500', // yellow
  '#9085e9', // violet
  '#d55181', // magenta
  '#d95926', // orange
  '#22b8cf', // cyan
  '#e66767', // red
];

/** Single-hue sequential ramp (brand violet) — near-zero → strong. */
export const SEQUENTIAL_VIOLET = ['#2a2250', '#4b3aa0', '#6b52d6', '#8b74f0', '#b7a6ff'];

export function catColor(i: number): string {
  return CATEGORICAL[i % CATEGORICAL.length];
}

/** Green for >=0, red for <0 — the diverging trading pair. */
export function signColor(v: number | null | undefined): string {
  if (v == null) return CHART.inkMuted;
  return v >= 0 ? CHART.pos : CHART.neg;
}

/** Shared Recharts tooltip container style (dark, elevated, subtle border). */
export const tooltipStyle: React.CSSProperties = {
  background: 'var(--bg-elevated)',
  border: '1px solid var(--border)',
  borderRadius: 8,
  padding: '8px 10px',
  fontSize: 11.5,
  fontFamily: 'var(--font-mono)',
  color: 'var(--text-primary)',
  boxShadow: '0 6px 20px rgba(0,0,0,0.35)',
};

export const axisTick = { fill: 'var(--text-muted)', fontSize: 10, fontFamily: 'var(--font-mono)' } as const;

export function fmtUsd(n: number | null | undefined, digits = 2): string {
  if (n == null || !Number.isFinite(n)) return '—';
  const a = Math.abs(n);
  const sign = n < 0 ? '-' : '';
  if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${sign}$${(a / 1e3).toFixed(1)}K`;
  return `${sign}$${a.toFixed(digits)}`;
}

export function fmtPct(n: number | null | undefined, digits = 1): string {
  if (n == null || !Number.isFinite(n)) return '—';
  const v = Math.abs(n) <= 1 ? n * 100 : n;
  return `${v.toFixed(digits)}%`;
}

export interface EquityCurvePoint { t?: string; pnl?: number; winner?: boolean }
export interface EquityChartData {
  equitySeries: Array<{ label: string; value: number }>;
  perTradePnl: Array<{ label: string; value: number; winner?: boolean }>;
  winLossData: Array<{ name: string; value: number; color: string }>;
  winRate: number | null;
  trades: number;
}

/**
 * Build cumulative-equity + per-trade-PnL + win/loss chart data from a
 * closed-trade equity curve ({t,pnl,winner}[]). Shared by every trader page so
 * the equity visualisations are consistent. `base` seeds the running equity.
 */
export function buildEquityCharts(
  curve: EquityCurvePoint[] | null | undefined,
  opts: { startingCapital?: number | null; equity?: number | null; totalPnl?: number | null } = {},
): EquityChartData {
  // equity_curve `pnl` is CUMULATIVE net PnL. Derive the PER-TRADE delta so the
  // per-trade bars and the equity reconstruction (run += value) are correct, and
  // count wins by the NET `winner` flag — never the sign of cumulative equity
  // (which counts "equity was above breakeven %", e.g. a phantom 70% vs true 37%).
  let prevCum = 0;
  const per = (curve ?? [])
    .map((p, i) => {
      const cum = Number(p?.pnl ?? 0);
      const delta = Number.isFinite(cum) ? cum - prevCum : NaN;
      if (Number.isFinite(cum)) prevCum = cum;
      return { label: `#${i + 1}`, value: delta, winner: p?.winner === true };
    })
    .filter((p) => Number.isFinite(p.value));
  const wins = per.filter((p) => p.winner === true).length;
  const losses = per.length - wins;
  const flat = 0;
  const base = opts.startingCapital
    ?? (opts.equity != null && opts.totalPnl != null ? opts.equity - opts.totalPnl : (opts.equity ?? 3000));
  let run = base;
  const equitySeries = per.length ? [{ label: 'Start', value: base }] : [];
  per.forEach((p, i) => { run += p.value; equitySeries.push({ label: `#${i + 1}`, value: run }); });
  const winLossData = [
    { name: 'Wins', value: wins, color: '#22c55e' },
    { name: 'Losses', value: losses, color: '#ef4444' },
    ...(flat > 0 ? [{ name: 'Flat', value: flat, color: '#f59e0b' }] : []),
  ].filter((d) => d.value > 0);
  return { equitySeries, perTradePnl: per, winLossData, winRate: per.length ? (wins / per.length) * 100 : null, trades: per.length };
}
