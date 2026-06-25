import { useState } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import meta from './meta';
import rbac from './rbac';
import route from './route';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

// ── Types ──────────────────────────────────────────────────────────────────

interface BrainStateEntry {
  symbol: string;
  timeframe: string;
  state: string;
  evidence_score: number;
  reasons: string[];
  allowed_actions: string[];
  scores?: Record<string, number>;
  error?: string;
  generated_utc?: string;
}

interface BrainOverview {
  generated_utc: string;
  symbols_processed: number;
  classifications_computed: number;
  errors: number;
  state_distribution: Record<string, number>;
  hedge_locked_symbols: string[];
  results_sample: BrainStateEntry[];
  places_real_order: boolean;
}

interface EntryGateStatus {
  symbol_exclusion_list: string[];
  allowed_entry_timeframes: string[];
  blocked_strategy_modes: string[];
  require_positive_expected_move: boolean;
  major_move_override_enabled: boolean;
}

interface HedgeLockEntry {
  pair_id: string;
  symbol: string;
  original_side: string;
  hedge_side: string;
  status: string;
  net_pnl_bps?: number;
  max_pair_drawdown_bps?: number;
  opened_utc?: string;
  expires_utc?: string;
}

interface HedgeLockStatus {
  active_pairs: HedgeLockEntry[];
  total_active: number;
  config_enabled: boolean;
}

interface AllBrainStates {
  states: BrainStateEntry[];
}

// ── Constants ──────────────────────────────────────────────────────────────

const STATE_COLOR: Record<string, string> = {
  NO_TRADE: '#6b7280',
  VOLATILITY_EXPANSION_UNSAFE: '#ef4444',
  DOUBLE_SIDED_LIQUIDATION_WHIPSAW: '#f97316',
  ORDERBOOK_TRAP_OR_SPOOF_RISK: '#dc2626',
  EMERGENCY_DE_RISK: '#b91c1c',
  HEDGE_LOCK_MANAGEMENT: '#8b5cf6',
  BREAKOUT_SQUEEZE_LONG: '#10b981',
  BREAKOUT_SQUEEZE_SHORT: '#f59e0b',
  LIQUIDITY_SWEEP_FALSE_BREAKOUT: '#ec4899',
  RANGE_MEAN_REVERSION: '#3b82f6',
  TREND_CONTINUATION_LONG: '#22c55e',
  TREND_CONTINUATION_SHORT: '#fb923c',
};

const STATE_EMOJI: Record<string, string> = {
  NO_TRADE: '⛔',
  VOLATILITY_EXPANSION_UNSAFE: '🔴',
  DOUBLE_SIDED_LIQUIDATION_WHIPSAW: '🌪',
  ORDERBOOK_TRAP_OR_SPOOF_RISK: '🪤',
  EMERGENCY_DE_RISK: '🚨',
  HEDGE_LOCK_MANAGEMENT: '🔒',
  BREAKOUT_SQUEEZE_LONG: '🚀',
  BREAKOUT_SQUEEZE_SHORT: '📉',
  LIQUIDITY_SWEEP_FALSE_BREAKOUT: '💧',
  RANGE_MEAN_REVERSION: '↔️',
  TREND_CONTINUATION_LONG: '📈',
  TREND_CONTINUATION_SHORT: '🔻',
};

const TF_ORDER = ['15m', '1h', '4h'];
const DANGER_STATES = new Set([
  'VOLATILITY_EXPANSION_UNSAFE',
  'DOUBLE_SIDED_LIQUIDATION_WHIPSAW',
  'ORDERBOOK_TRAP_OR_SPOOF_RISK',
  'EMERGENCY_DE_RISK',
]);
const OPPORTUNITY_STATES = new Set([
  'BREAKOUT_SQUEEZE_LONG',
  'BREAKOUT_SQUEEZE_SHORT',
  'TREND_CONTINUATION_LONG',
  'TREND_CONTINUATION_SHORT',
  'RANGE_MEAN_REVERSION',
]);

// ── Helpers ────────────────────────────────────────────────────────────────

function stateLabel(state: string): string {
  return (STATE_EMOJI[state] ?? '•') + ' ' + state.replace(/_/g, ' ');
}

function scoreBar(score: number): JSX.Element {
  const pct = Math.min(100, Math.round(score * 100));
  const color = score >= 0.7 ? '#10b981' : score >= 0.5 ? '#f59e0b' : '#6b7280';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
      <div style={{ width: 60, height: 6, background: '#1f2937', borderRadius: 3 }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontSize: 10, color: '#9ca3af' }}>{pct}%</span>
    </div>
  );
}

function ageSecs(utc?: string): string {
  if (!utc) return '—';
  const diff = Math.floor((Date.now() - new Date(utc).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

// ── State Cell ─────────────────────────────────────────────────────────────

function StateCell({ entry }: { entry: BrainStateEntry | undefined }) {
  const [open, setOpen] = useState(false);
  if (!entry) return <td style={tdStyle('#111827')}>—</td>;
  const color = STATE_COLOR[entry.state] ?? '#6b7280';
  return (
    <td
      style={{ ...tdStyle(color + '22'), cursor: 'pointer', border: `1px solid ${color}44` }}
      onClick={() => setOpen(o => !o)}
      title={entry.reasons?.join(' | ')}
    >
      <div style={{ color, fontWeight: 600, fontSize: 10 }}>{STATE_EMOJI[entry.state] ?? '•'} {entry.state.replace(/_/g, ' ')}</div>
      {scoreBar(entry.evidence_score)}
      {open && (
        <div style={{ marginTop: 6, fontSize: 9, color: '#d1d5db' }}>
          {entry.reasons?.map((r, i) => <div key={i}>• {r}</div>)}
          {entry.allowed_actions?.length > 0 && (
            <div style={{ marginTop: 3, color: '#6ee7b7' }}>→ {entry.allowed_actions.join(', ')}</div>
          )}
          <div style={{ color: '#6b7280', marginTop: 2 }}>{ageSecs(entry.generated_utc)}</div>
        </div>
      )}
    </td>
  );
}

// ── State Distribution Chart ───────────────────────────────────────────────

function StateDistChart({ dist }: { dist: Record<string, number> }) {
  const total = Object.values(dist).reduce((a, b) => a + b, 0) || 1;
  const sorted = Object.entries(dist).sort((a, b) => b[1] - a[1]);
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
      {sorted.map(([state, count]) => {
        const pct = Math.round((count / total) * 100);
        const color = STATE_COLOR[state] ?? '#6b7280';
        return (
          <div key={state} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: color }} />
            <span style={{ fontSize: 10, color: '#d1d5db' }}>{state.replace(/_/g, ' ')}</span>
            <span style={{ fontSize: 10, color, fontWeight: 700 }}>{count} ({pct}%)</span>
          </div>
        );
      })}
    </div>
  );
}

// ── Styles ─────────────────────────────────────────────────────────────────

const S = {
  page: { background: '#0d1117', minHeight: '100vh', padding: '16px 20px', color: '#e5e7eb', fontFamily: 'monospace' },
  header: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap' as const, gap: 8 },
  title: { fontSize: 20, fontWeight: 700, color: '#f9fafb' },
  badge: (color: string): React.CSSProperties => ({
    padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600,
    background: color + '22', border: `1px solid ${color}44`, color,
  }),
  section: { marginBottom: 20 },
  sectionTitle: { fontSize: 13, fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase' as const, marginBottom: 8, letterSpacing: 1 },
  card: { background: '#161b22', border: '1px solid #30363d', borderRadius: 8, padding: 14, marginBottom: 10 },
  grid3: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 8 },
  metric: { background: '#0d1117', border: '1px solid #21262d', borderRadius: 6, padding: 10 },
  metricLabel: { fontSize: 10, color: '#6b7280', textTransform: 'uppercase' as const, letterSpacing: 1 },
  metricValue: { fontSize: 15, fontWeight: 700, color: '#e5e7eb', marginTop: 3 },
  tableWrap: { overflowX: 'auto' as const, maxHeight: 480 },
  table: { borderCollapse: 'collapse' as const, fontSize: 11, width: '100%' },
  th: { padding: '6px 10px', background: '#161b22', color: '#9ca3af', textAlign: 'left' as const, position: 'sticky' as const, top: 0, zIndex: 1, whiteSpace: 'nowrap' as const, borderBottom: '1px solid #30363d' },
  noData: { color: '#6b7280', fontSize: 12, padding: 20, textAlign: 'center' as const },
  safetyBanner: { background: '#1a0000', border: '2px solid #7f1d1d', borderRadius: 8, padding: '10px 16px', marginBottom: 16, color: '#fca5a5', fontSize: 12 },
};

function tdStyle(bg: string): React.CSSProperties {
  return { padding: '5px 8px', verticalAlign: 'top', background: bg, whiteSpace: 'nowrap' };
}

function Metric({ label, value, color }: { label: string; value: unknown; color?: string }) {
  return (
    <div style={S.metric}>
      <div style={S.metricLabel}>{label}</div>
      <div style={{ ...S.metricValue, color: color ?? '#e5e7eb' }}>{String(value ?? '—')}</div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function MarketBrainPage(): JSX.Element {
  const [symbolFilter, setSymbolFilter] = useState('');
  const [stateFilter, setStateFilter] = useState('ALL');

  const overview = useRealtimeResource<BrainOverview>({
    url: '/api/v2/market-brain/overview',
    source: 'market_brain_overview',
    pollIntervalMs: 15000,
    staleThresholdMs: 60000,
  });

  const allStates = useRealtimeResource<AllBrainStates>({
    url: '/api/v2/market-brain/state',
    source: 'market_brain_states',
    pollIntervalMs: 15000,
    staleThresholdMs: 60000,
  });

  const entryGate = useRealtimeResource<EntryGateStatus>({
    url: '/api/v2/market-brain/entry-gate-status',
    source: 'entry_gate_status',
    pollIntervalMs: 60000,
    staleThresholdMs: 300000,
  });

  const hedgeLock = useRealtimeResource<HedgeLockStatus>({
    url: '/api/v2/market-brain/hedge-lock-status',
    source: 'hedge_lock_status',
    pollIntervalMs: 10000,
    staleThresholdMs: 30000,
  });

  const ov = overview.envelope.data;
  const states: BrainStateEntry[] = allStates.envelope.data?.states ?? ov?.results_sample ?? [];
  const eg = entryGate.envelope.data;
  const hl = hedgeLock.envelope.data;

  // Build symbol→TF→entry lookup
  const stateMap = new Map<string, Map<string, BrainStateEntry>>();
  for (const s of states) {
    if (!stateMap.has(s.symbol)) stateMap.set(s.symbol, new Map());
    stateMap.get(s.symbol)!.set(s.timeframe, s);
  }

  const allSymbols = Array.from(stateMap.keys()).sort();
  const filteredSymbols = allSymbols.filter(sym => {
    const matchesText = !symbolFilter || sym.toLowerCase().includes(symbolFilter.toLowerCase());
    if (!matchesText) return false;
    if (stateFilter === 'ALL') return true;
    if (stateFilter === 'DANGER') {
      return TF_ORDER.some(tf => DANGER_STATES.has(stateMap.get(sym)?.get(tf)?.state ?? ''));
    }
    if (stateFilter === 'OPPORTUNITY') {
      return TF_ORDER.some(tf => OPPORTUNITY_STATES.has(stateMap.get(sym)?.get(tf)?.state ?? ''));
    }
    return TF_ORDER.some(tf => stateMap.get(sym)?.get(tf)?.state === stateFilter);
  });

  // Opportunity alerts
  const opportunities = states.filter(s => OPPORTUNITY_STATES.has(s.state));
  const dangers = states.filter(s => DANGER_STATES.has(s.state));

  return (
    <div style={S.page}>
      {/* Header */}
      <div style={S.header}>
        <div>
          <div style={S.title}>Market State Brain</div>
          <div style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>{meta.description}</div>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <span style={S.badge('#6ee7b7')}>MARKET DATA LIVE</span>
          <span style={S.badge('#ef4444')}>EXECUTION RESTRICTED</span>
          <span style={S.badge('#60a5fa')}>ORDER SUBMISSION DISABLED</span>
          {ov && <span style={S.badge('#9ca3af')}>Updated {ageSecs(ov.generated_utc)}</span>}
        </div>
      </div>

      {/* Safety Banner */}
      <div style={S.safetyBanner}>
        Platform status: realtime market intelligence and risk-governed execution workflows. HedgeLock requires explicit operator approval.
      </div>

      {/* Overview Metrics */}
      <div style={S.section}>
        <div style={S.sectionTitle}>System Overview</div>
        <div style={S.card}>
          <div style={S.grid3}>
            <Metric label="Symbols Processed" value={ov?.symbols_processed ?? '—'} />
            <Metric label="Classifications" value={ov?.classifications_computed ?? '—'} />
            <Metric label="Errors" value={ov?.errors ?? '—'} color={ov?.errors ? '#ef4444' : '#10b981'} />
            <Metric label="Opportunity Signals" value={opportunities.length} color={opportunities.length > 0 ? '#10b981' : '#6b7280'} />
            <Metric label="Danger Signals" value={dangers.length} color={dangers.length > 0 ? '#ef4444' : '#6b7280'} />
            <Metric label="Hedge-Locked Symbols" value={ov?.hedge_locked_symbols?.length ?? 0} color="#8b5cf6" />
            <Metric label="Real Orders Placed" value="NEVER" color="#10b981" />
            <Metric label="Live Gate" value="BLOCKED" color="#ef4444" />
          </div>
          {ov?.state_distribution && Object.keys(ov.state_distribution).length > 0 && (
            <>
              <div style={{ ...S.sectionTitle, marginTop: 12 }}>State Distribution</div>
              <StateDistChart dist={ov.state_distribution} />
            </>
          )}
        </div>
      </div>

      {/* Opportunity Alerts */}
      {opportunities.length > 0 && (
        <div style={S.section}>
          <div style={S.sectionTitle}>⚡ Active Opportunities ({opportunities.length})</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {opportunities.slice(0, 30).map((s, i) => {
              const color = STATE_COLOR[s.state] ?? '#10b981';
              return (
                <div key={i} style={{ background: color + '18', border: `1px solid ${color}44`, borderRadius: 6, padding: '6px 10px' }}>
                  <div style={{ color, fontWeight: 700, fontSize: 11 }}>{s.symbol} {s.timeframe}</div>
                  <div style={{ fontSize: 10, color: '#d1d5db' }}>{STATE_EMOJI[s.state]} {s.state.replace(/_/g, ' ')}</div>
                  <div style={{ fontSize: 10, color: '#9ca3af' }}>{Math.round(s.evidence_score * 100)}% confidence</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Danger Alerts */}
      {dangers.length > 0 && (
        <div style={S.section}>
          <div style={S.sectionTitle}>⛔ Active Danger Zones ({dangers.length})</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {dangers.slice(0, 20).map((s, i) => {
              const color = STATE_COLOR[s.state] ?? '#ef4444';
              return (
                <div key={i} style={{ background: '#1a0000', border: `1px solid ${color}44`, borderRadius: 6, padding: '6px 10px' }}>
                  <div style={{ color: '#ef4444', fontWeight: 700, fontSize: 11 }}>{s.symbol} {s.timeframe}</div>
                  <div style={{ fontSize: 10, color: '#fca5a5' }}>{STATE_EMOJI[s.state]} {s.state.replace(/_/g, ' ')}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Multi-TF State Grid */}
      <div style={S.section}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8, flexWrap: 'wrap' }}>
          <div style={S.sectionTitle}>Multi-TF State Grid ({filteredSymbols.length} symbols)</div>
          <input
            placeholder="Filter symbol…"
            value={symbolFilter}
            onChange={e => setSymbolFilter(e.target.value)}
            style={{ background: '#0d1117', border: '1px solid #30363d', borderRadius: 4, color: '#e5e7eb', padding: '4px 8px', fontSize: 11 }}
          />
          <select
            value={stateFilter}
            onChange={e => setStateFilter(e.target.value)}
            style={{ background: '#0d1117', border: '1px solid #30363d', borderRadius: 4, color: '#e5e7eb', padding: '4px 8px', fontSize: 11 }}
          >
            <option value="ALL">All States</option>
            <option value="OPPORTUNITY">Opportunities</option>
            <option value="DANGER">Danger</option>
            {Object.keys(STATE_COLOR).map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div style={{ ...S.card, padding: 0 }}>
          {filteredSymbols.length === 0 ? (
            <div style={S.noData}>
              {states.length === 0
                ? 'Market state stream connecting. Waiting for live classifications.'
                : 'No symbols match the current filter.'}
            </div>
          ) : (
            <div style={S.tableWrap}>
              <table style={S.table}>
                <thead>
                  <tr>
                    <th style={S.th}>Symbol</th>
                    {TF_ORDER.map(tf => <th key={tf} style={S.th}>{tf}</th>)}
                    <th style={S.th}>Hedge Lock</th>
                    <th style={S.th}>Entry Gate</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredSymbols.map(sym => {
                    const tfMap = stateMap.get(sym)!;
                    const isHedgeLocked = ov?.hedge_locked_symbols?.includes(sym) ?? false;
                    const isBlocked = eg?.symbol_exclusion_list?.includes(sym) ?? false;
                    return (
                      <tr key={sym}>
                        <td style={{ ...tdStyle('#0d1117'), fontWeight: 700, color: '#e5e7eb', fontSize: 11 }}>
                          {sym}
                          {isHedgeLocked && <span style={{ marginLeft: 4, fontSize: 9, color: '#8b5cf6' }}>🔒 LOCKED</span>}
                          {isBlocked && <span style={{ marginLeft: 4, fontSize: 9, color: '#ef4444' }}>⛔ EXCL</span>}
                        </td>
                        {TF_ORDER.map(tf => <StateCell key={tf} entry={tfMap.get(tf)} />)}
                        <td style={tdStyle(isHedgeLocked ? '#1a0a2e' : '#0d1117')}>
                          <span style={{ color: isHedgeLocked ? '#8b5cf6' : '#374151', fontSize: 11 }}>
                            {isHedgeLocked ? '🔒 ACTIVE' : '—'}
                          </span>
                        </td>
                        <td style={tdStyle(isBlocked ? '#1a0000' : '#0d1117')}>
                          <span style={{ color: isBlocked ? '#ef4444' : '#10b981', fontSize: 11 }}>
                            {isBlocked ? '⛔ BLOCKED' : '✓ ALLOWED'}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Entry Gate Panel */}
      <div style={S.section}>
        <div style={S.sectionTitle}>P0 Entry Gate Config</div>
        <div style={S.card}>
          {eg ? (
            <div>
              <div style={S.grid3}>
                <Metric label="Blocked Symbols" value={eg.symbol_exclusion_list?.length ?? 0} color="#ef4444" />
                <Metric label="Allowed TFs" value={eg.allowed_entry_timeframes?.join(', ') ?? '—'} color="#10b981" />
                <Metric label="Blocked Modes" value={eg.blocked_strategy_modes?.join(', ') ?? '—'} color="#f97316" />
                <Metric label="Req. Positive Expected Move" value={String(eg.require_positive_expected_move)} />
                <Metric label="Major Move Override" value={String(eg.major_move_override_enabled)} color="#f59e0b" />
              </div>
              {eg.symbol_exclusion_list?.length > 0 && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ fontSize: 11, color: '#6b7280', marginBottom: 4 }}>Zero-Edge Symbols (blocked from new entries)</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {eg.symbol_exclusion_list.map(s => (
                      <span key={s} style={{ background: '#1a0000', border: '1px solid #7f1d1d', borderRadius: 4, padding: '2px 8px', color: '#fca5a5', fontSize: 11 }}>{s}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div style={S.noData}>Entry gate data loading… ({entryGate.error ?? 'fetching'})</div>
          )}
        </div>
      </div>

      {/* HedgeLock Panel */}
      <div style={S.section}>
        <div style={S.sectionTitle}>HedgeLock Status</div>
        <div style={S.card}>
          <div style={{ marginBottom: 10, display: 'flex', gap: 12 }}>
            <Metric label="Config Enabled" value={hl?.config_enabled ? 'YES' : 'NO (DEFAULT OFF)'} color={hl?.config_enabled ? '#f97316' : '#6b7280'} />
            <Metric label="Active Pairs" value={hl?.total_active ?? 0} color="#8b5cf6" />
          </div>
          <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 8 }}>
            HedgeLock is disabled by default. Enabling requires operator approval (dangerous setting per CLAUDE.md). Only activates after profitable excursion ≥ 25 bps.
          </div>
          {hl?.active_pairs?.length ? (
            <div style={S.tableWrap}>
              <table style={S.table}>
                <thead>
                  <tr>
                    {['Pair ID', 'Symbol', 'Original Side', 'Hedge Side', 'Status', 'Net PnL (bps)', 'Opened'].map(h => (
                      <th key={h} style={S.th}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {hl.active_pairs.map(p => (
                    <tr key={p.pair_id}>
                      <td style={tdStyle('#0d1117')}><span style={{ fontSize: 10 }}>{p.pair_id}</span></td>
                      <td style={tdStyle('#0d1117')}><b>{p.symbol}</b></td>
                      <td style={tdStyle(p.original_side === 'LONG' ? '#022c22' : '#1a0000')}><span style={{ color: p.original_side === 'LONG' ? '#34d399' : '#f87171' }}>{p.original_side}</span></td>
                      <td style={tdStyle(p.hedge_side === 'SHORT' ? '#1a0000' : '#022c22')}><span style={{ color: p.hedge_side === 'SHORT' ? '#f87171' : '#34d399' }}>{p.hedge_side}</span></td>
                      <td style={tdStyle('#0d1117')}><span style={{ color: '#8b5cf6' }}>{p.status}</span></td>
                      <td style={tdStyle('#0d1117')}><span style={{ color: (p.net_pnl_bps ?? 0) >= 0 ? '#10b981' : '#ef4444' }}>{p.net_pnl_bps?.toFixed(1) ?? '—'}</span></td>
                      <td style={tdStyle('#0d1117')}><span style={{ fontSize: 10, color: '#9ca3af' }}>{ageSecs(p.opened_utc)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div style={{ color: '#374151', fontSize: 11 }}>No active hedge lock pairs.</div>
          )}
        </div>
      </div>

      {/* 12-State Legend */}
      <div style={S.section}>
        <div style={S.sectionTitle}>12-State Classification Legend</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 6 }}>
          {Object.entries(STATE_COLOR).map(([state, color]) => (
            <div key={state} style={{ display: 'flex', alignItems: 'center', gap: 8, background: '#161b22', border: `1px solid ${color}33`, borderRadius: 6, padding: '6px 10px' }}>
              <div style={{ width: 10, height: 10, borderRadius: '50%', background: color, flexShrink: 0 }} />
              <div>
                <div style={{ fontSize: 11, color, fontWeight: 600 }}>{STATE_EMOJI[state]} {state.replace(/_/g, ' ')}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Footer */}
      <div style={{ marginTop: 24, fontSize: 10, color: '#374151', textAlign: 'center' }}>
        Market Brain Worker: v2/backend/app/cli/v2_market_state_brain_worker.py | Poll interval: 15s | TTL: 120s | Classifier: v2/backend/app/services/market_state_brain/classifier.py | NO REAL ORDERS | LIVE GATE BLOCKED
      </div>
    </div>
  );
}
