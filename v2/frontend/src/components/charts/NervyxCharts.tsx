/**
 * Reusable NERVYX chart primitives (Recharts) for trader surfaces.
 * Theme-matched, dark-first, hover tooltips by default, direct labels for
 * identity so colour is never the sole encoding. See nervyxChartTheme.ts.
 */
import {
  ResponsiveContainer, AreaChart, Area, BarChart, Bar, Cell,
  PieChart, Pie, RadialBarChart, RadialBar, XAxis, YAxis, CartesianGrid,
  Tooltip, ReferenceLine,
} from 'recharts';
import {
  CHART, catColor, signColor, tooltipStyle, axisTick, fmtUsd, fmtPct,
} from './nervyxChartTheme';

export function ChartFrame({ title, subtitle, right, height = 180, children }: {
  title?: string; subtitle?: string; right?: React.ReactNode; height?: number; children: React.ReactNode;
}): JSX.Element {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
      {(title || right) && (
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
          <div style={{ minWidth: 0 }}>
            {title && <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{title}</div>}
            {subtitle && <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{subtitle}</div>}
          </div>
          {right && <div style={{ flexShrink: 0 }}>{right}</div>}
        </div>
      )}
      <div style={{ width: '100%', height }}>{children}</div>
    </div>
  );
}

function TipBox({ rows }: { rows: Array<{ label: string; value: string; color?: string }> }): JSX.Element {
  return (
    <div style={tooltipStyle}>
      {rows.map((r, i) => (
        <div key={i} style={{ display: 'flex', gap: 10, justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--text-muted)' }}>
            {r.color && <span style={{ width: 8, height: 8, borderRadius: 2, background: r.color, display: 'inline-block' }} />}{r.label}
          </span>
          <span style={{ color: r.color ?? 'var(--text-primary)', fontWeight: 700 }}>{r.value}</span>
        </div>
      ))}
    </div>
  );
}

// ── Equity / value trend (area, gradient, crosshair tooltip) ────────────────
export function EquityAreaChart({ data, height = 180, valuePrefix = '$', color = CHART.accent }: {
  data: Array<{ label: string; value: number }>; height?: number; valuePrefix?: string; color?: string;
}): JSX.Element {
  const vals = data.map((d) => d.value);
  const min = Math.min(...vals), max = Math.max(...vals);
  const pad = (max - min) * 0.08 || Math.abs(max) * 0.02 || 1;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 6, right: 8, left: 2, bottom: 0 }}>
        <defs>
          <linearGradient id="nvxEquityFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.35} />
            <stop offset="100%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={CHART.grid} vertical={false} />
        <XAxis dataKey="label" tick={axisTick} tickLine={false} axisLine={{ stroke: CHART.grid }} minTickGap={24} />
        <YAxis domain={[min - pad, max + pad]} tick={axisTick} tickLine={false} axisLine={false} width={52}
          tickFormatter={(v) => `${valuePrefix}${Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 })}`} />
        <Tooltip cursor={{ stroke: color, strokeWidth: 1, strokeDasharray: '3 3' }}
          content={({ active, payload, label }) => active && payload?.length
            ? <TipBox rows={[{ label: String(label), value: `${valuePrefix}${Number(payload[0].value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, color }]} /> : null} />
        <Area type="monotone" dataKey="value" stroke={color} strokeWidth={2} fill="url(#nvxEquityFill)" dot={false} activeDot={{ r: 4, strokeWidth: 0 }} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// ── Diverging bars (+/- coloured, sign is the secondary encoding) ───────────
export function PnLBars({ data, height = 180, usd = true }: {
  data: Array<{ label: string; value: number }>; height?: number; usd?: boolean;
}): JSX.Element {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 2, bottom: 0 }}>
        <CartesianGrid stroke={CHART.grid} vertical={false} />
        <XAxis dataKey="label" tick={axisTick} tickLine={false} axisLine={{ stroke: CHART.grid }} interval={0} minTickGap={2} />
        <YAxis tick={axisTick} tickLine={false} axisLine={false} width={usd ? 52 : 40}
          tickFormatter={(v) => usd ? fmtUsd(Number(v), 0) : String(v)} />
        <ReferenceLine y={0} stroke={CHART.grid} />
        <Tooltip cursor={{ fill: 'rgba(148,163,184,0.08)' }}
          content={({ active, payload, label }) => active && payload?.length
            ? <TipBox rows={[{ label: String(label), value: usd ? fmtUsd(Number(payload[0].value)) : String(payload[0].value), color: signColor(Number(payload[0].value)) }]} /> : null} />
        <Bar dataKey="value" radius={[3, 3, 0, 0]} maxBarSize={46}>
          {data.map((d, i) => <Cell key={i} fill={signColor(d.value)} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ── Donut (composition; direct labels + legend + centre total) ──────────────
export function Donut({ data, height = 180, centerLabel, centerValue, palette }: {
  data: Array<{ name: string; value: number; color?: string }>; height?: number;
  centerLabel?: string; centerValue?: string; palette?: string[];
}): JSX.Element {
  const total = data.reduce((s, d) => s + (d.value || 0), 0);
  const colored = data.map((d, i) => ({ ...d, color: d.color ?? (palette ? palette[i % palette.length] : catColor(i)) }));
  return (
    <div style={{ position: 'relative', width: '100%', height }}>
      <ResponsiveContainer width="100%" height={height}>
        <PieChart>
          <Pie data={colored} dataKey="value" nameKey="name" innerRadius="62%" outerRadius="88%" paddingAngle={2} stroke="var(--bg-panel)" strokeWidth={2}>
            {colored.map((d, i) => <Cell key={i} fill={d.color} />)}
          </Pie>
          <Tooltip content={({ active, payload }) => active && payload?.length
            ? <TipBox rows={[{ label: String(payload[0].name), value: `${payload[0].value} · ${total ? ((Number(payload[0].value) / total) * 100).toFixed(0) : 0}%`, color: (payload[0].payload as { color?: string }).color }]} /> : null} />
        </PieChart>
      </ResponsiveContainer>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none' }}>
        {centerValue && <span style={{ fontSize: 20, fontWeight: 800, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>{centerValue}</span>}
        {centerLabel && <span style={{ fontSize: 9.5, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{centerLabel}</span>}
      </div>
    </div>
  );
}

export function DonutLegend({ data, palette }: { data: Array<{ name: string; value: number; color?: string }>; palette?: string[] }): JSX.Element {
  const total = data.reduce((s, d) => s + (d.value || 0), 0);
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 12px', marginTop: 6 }}>
      {data.map((d, i) => (
        <span key={d.name} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 10.5, fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: d.color ?? (palette ? palette[i % palette.length] : catColor(i)) }} />
          {d.name} <b style={{ color: 'var(--text-primary)' }}>{total ? ((d.value / total) * 100).toFixed(0) : 0}%</b>
        </span>
      ))}
    </div>
  );
}

// ── Radial gauge (single magnitude 0-100%, sequential feel) ─────────────────
export function RadialGauge({ value, height = 150, label, color }: {
  value: number | null | undefined; height?: number; label?: string; color?: string;
}): JSX.Element {
  const pct = value == null ? 0 : Math.max(0, Math.min(100, Math.abs(value) <= 1 ? value * 100 : value));
  const c = color ?? (pct >= 60 ? CHART.pos : pct >= 45 ? CHART.neutral : CHART.neg);
  const data = [{ name: label ?? 'value', value: pct, fill: c }];
  return (
    <div style={{ position: 'relative', width: '100%', height }}>
      <ResponsiveContainer width="100%" height={height}>
        <RadialBarChart innerRadius="66%" outerRadius="100%" data={data} startAngle={220} endAngle={-40}>
          <defs>
            <linearGradient id="nvxGaugeTrack" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="rgba(148,163,184,0.10)" />
              <stop offset="100%" stopColor="rgba(148,163,184,0.10)" />
            </linearGradient>
          </defs>
          <RadialBar background={{ fill: 'rgba(148,163,184,0.10)' }} dataKey="value" cornerRadius={8} />
        </RadialBarChart>
      </ResponsiveContainer>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none' }}>
        <span style={{ fontSize: 24, fontWeight: 800, fontFamily: 'var(--font-mono)', color: c }}>{value == null ? '—' : `${pct.toFixed(1)}%`}</span>
        {label && <span style={{ fontSize: 9.5, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</span>}
      </div>
    </div>
  );
}

// ── Inline sparkline (tiny trend, no axes) ──────────────────────────────────
export function Sparkline({ data, height = 40, color = CHART.accent }: {
  data: number[]; height?: number; color?: string;
}): JSX.Element {
  const pts = data.map((v, i) => ({ i, value: v }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={pts} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="nvxSpark" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.3} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area type="monotone" dataKey="value" stroke={color} strokeWidth={1.5} fill="url(#nvxSpark)" dot={false} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export { fmtUsd, fmtPct };
