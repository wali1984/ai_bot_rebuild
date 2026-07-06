/**
 * Realtime host + GPU utilisation panel, shared by Monitor Center and
 * System Health so both pages render the exact same data from the exact
 * same source: /api/v2/system/metrics (streamed via /api/v2/ws/resource).
 */
import { useMemo } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';

// Categorical assignments (fixed order) from the validated NERVYX chart set.
const CPU_COLOR = '#219E94';
const MEM_COLOR = '#8B6EFF';
const GPU_COLOR = '#CC7D22';
const NET_RX_COLOR = '#4E92DE';
const NET_TX_COLOR = '#C95F84';

interface GpuInfo {
  index: number;
  name: string;
  utilization_pct: number | null;
  vram_used_mb: number | null;
  vram_total_mb: number | null;
  temperature_c: number | null;
  power_draw_w: number | null;
  power_limit_w: number | null;
}

interface HistoryPoint {
  timestamp: string;
  cpu_pct: number | null;
  memory_pct: number | null;
  gpu_pct: number | null;
  gpu_vram_used_mb: number | null;
  recv_bytes_per_sec: number | null;
  sent_bytes_per_sec: number | null;
}

interface SystemMetricsData {
  cpu: { total_pct: number; core_count: number; load_1m: number; load_5m: number; load_15m: number };
  memory: { used_mb: number; total_mb: number; percent: number; swap_used_mb: number; swap_total_mb: number };
  disk: { mount: string; used_gb: number; total_gb: number; percent: number | null };
  network: { recv_bytes_per_sec: number | null; sent_bytes_per_sec: number | null };
  gpus: GpuInfo[];
  trainer_gpu_view: {
    gpu_name?: string | null;
    cuda_active?: boolean;
    utilization_pct?: number | null;
    training_steps_per_minute?: number | null;
  } | null;
  history: HistoryPoint[];
}

const panelStyle: React.CSSProperties = {
  background: 'var(--bg-panel)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-md, 10px)',
  padding: '14px 16px 8px',
  minWidth: 0,
};

const tooltipStyle: React.CSSProperties = {
  background: 'var(--bg-elevated, #171E2E)',
  border: '1px solid var(--border)',
  borderRadius: 6,
  fontSize: 12,
  color: 'var(--text-primary)',
};

function Gauge({ label, value, suffix, color, detail }: { label: string; value: string; suffix?: string; color: string; detail?: string }): JSX.Element {
  return (
    <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md, 10px)', padding: '12px 14px' }}>
      <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)' }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, fontFamily: 'var(--font-mono)', color, marginTop: 2 }}>
        {value}
        {suffix && <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 3 }}>{suffix}</span>}
      </div>
      {detail && <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 2 }}>{detail}</div>}
    </div>
  );
}

function fmtKbs(bytesPerSec: number | null | undefined): string {
  if (bytesPerSec == null) return '—';
  const kb = bytesPerSec / 1024;
  if (kb >= 1024) return `${(kb / 1024).toFixed(1)} MB/s`;
  return `${kb.toFixed(0)} KB/s`;
}

export function SystemResourcesPanel(): JSX.Element {
  const metrics = useRealtimeResource<SystemMetricsData>({
    url: '/api/v2/system/metrics',
    source: '/api/v2/system/metrics',
    source_type: 'websocket',
    pollIntervalMs: 2_000,
    staleThresholdMs: 15_000,
    mode: 'read_only',
  });
  const data = metrics.envelope.data;
  const history = useMemo(
    () => (data?.history ?? []).map((point) => ({ ...point, at: point.timestamp.slice(11, 19) })),
    [data],
  );
  const gpu = data?.gpus?.[0] ?? null;
  const stale = metrics.envelope.freshness_status !== 'fresh';

  if (metrics.loading && !data) {
    return <p style={{ color: 'var(--text-muted)', fontSize: 13, margin: '12px 0' }}>Connecting system metrics stream…</p>;
  }
  if (!data) {
    return <p style={{ color: 'var(--sell, #FF5D7A)', fontSize: 13, margin: '12px 0' }}>System metrics unavailable.</p>;
  }

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))', gap: 12, marginBottom: 14 }}>
        <Gauge
          label="CPU"
          value={data.cpu.total_pct.toFixed(0)}
          suffix="%"
          color={CPU_COLOR}
          detail={`${data.cpu.core_count} cores · load ${data.cpu.load_1m.toFixed(2)}`}
        />
        <Gauge
          label="Memory"
          value={data.memory.percent.toFixed(0)}
          suffix="%"
          color={MEM_COLOR}
          detail={`${(data.memory.used_mb / 1024).toFixed(1)} / ${(data.memory.total_mb / 1024).toFixed(0)} GB`}
        />
        <Gauge
          label="GPU"
          value={gpu?.utilization_pct != null ? gpu.utilization_pct.toFixed(0) : '—'}
          suffix="%"
          color={GPU_COLOR}
          detail={gpu ? `${gpu.name}${gpu.temperature_c != null ? ` · ${gpu.temperature_c}°C` : ''}` : 'no GPU telemetry'}
        />
        <Gauge
          label="VRAM"
          value={gpu?.vram_used_mb != null ? (gpu.vram_used_mb / 1024).toFixed(1) : '—'}
          suffix={gpu?.vram_total_mb != null ? `/ ${(gpu.vram_total_mb / 1024).toFixed(0)} GB` : 'GB'}
          color={GPU_COLOR}
          detail={data.trainer_gpu_view?.cuda_active ? `trainer CUDA active · ${data.trainer_gpu_view.training_steps_per_minute?.toFixed(0) ?? '—'} steps/min` : 'trainer idle'}
        />
        <Gauge
          label="Disk"
          value={data.disk.percent != null ? data.disk.percent.toFixed(0) : '—'}
          suffix="%"
          color={CPU_COLOR}
          detail={`${data.disk.used_gb.toFixed(0)} / ${data.disk.total_gb.toFixed(0)} GB`}
        />
        <Gauge
          label="Network"
          value={fmtKbs(data.network.recv_bytes_per_sec)}
          color={NET_RX_COLOR}
          detail={`↑ ${fmtKbs(data.network.sent_bytes_per_sec)}`}
        />
      </div>

      {history.length >= 2 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 14 }}>
          <div style={panelStyle}>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 8 }}>
              Utilisation % {stale ? '· reconnecting…' : '· realtime'}
            </div>
            <ResponsiveContainer width="100%" height={190}>
              <LineChart data={history} margin={{ left: 0, right: 12 }}>
                <CartesianGrid stroke="var(--chart-grid, #1F2937)" strokeDasharray="2 4" vertical={false} />
                <XAxis dataKey="at" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} minTickGap={40} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: 'var(--text-muted)' }} width={34} />
                <Tooltip contentStyle={tooltipStyle} />
                <Line type="monotone" dataKey="cpu_pct" name="CPU" stroke={CPU_COLOR} strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line type="monotone" dataKey="memory_pct" name="Memory" stroke={MEM_COLOR} strokeWidth={2} dot={false} isAnimationActive={false} />
                <Line type="monotone" dataKey="gpu_pct" name="GPU" stroke={GPU_COLOR} strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
            <div style={{ display: 'flex', gap: 14, marginTop: 6, fontSize: 12, color: 'var(--text-secondary)' }}>
              {[['CPU', CPU_COLOR], ['Memory', MEM_COLOR], ['GPU', GPU_COLOR]].map(([name, color]) => (
                <span key={name} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ width: 10, height: 2, background: color, display: 'inline-block' }} />
                  {name}
                </span>
              ))}
            </div>
          </div>

          <div style={panelStyle}>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 8 }}>Network throughput</div>
            <ResponsiveContainer width="100%" height={190}>
              <AreaChart data={history} margin={{ left: 0, right: 12 }}>
                <CartesianGrid stroke="var(--chart-grid, #1F2937)" strokeDasharray="2 4" vertical={false} />
                <XAxis dataKey="at" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} minTickGap={40} />
                <YAxis tick={{ fontSize: 10, fill: 'var(--text-muted)' }} width={52} tickFormatter={(v: number) => fmtKbs(v)} />
                <Tooltip contentStyle={tooltipStyle} formatter={(value) => fmtKbs(Number(value))} />
                <Area type="monotone" dataKey="recv_bytes_per_sec" name="Down" stroke={NET_RX_COLOR} fill={NET_RX_COLOR} fillOpacity={0.18} strokeWidth={2} isAnimationActive={false} />
                <Area type="monotone" dataKey="sent_bytes_per_sec" name="Up" stroke={NET_TX_COLOR} fill={NET_TX_COLOR} fillOpacity={0.18} strokeWidth={2} isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
            <div style={{ display: 'flex', gap: 14, marginTop: 6, fontSize: 12, color: 'var(--text-secondary)' }}>
              {[['Down', NET_RX_COLOR], ['Up', NET_TX_COLOR]].map(([name, color]) => (
                <span key={name} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ width: 10, height: 2, background: color, display: 'inline-block' }} />
                  {name}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
