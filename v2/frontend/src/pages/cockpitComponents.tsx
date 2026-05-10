import type { ReactNode } from 'react';
import type { Candle, CockpitPayload, DecisionRow, ExchangeConnector, Freshness, MonitorRow, Phase3cRuntimeMonitorPayload, QuarantinePayload, RedisExportCapacityPayload, RedisFullExportPayload, RedisHumanApprovalPayload, RedisMemoryPressurePayload, SettingRow, SystemAtlasGapRemediationPayload, SystemAtlasPayload } from './cockpitData';
import { statusClass, valueText } from './cockpitData';

export function CockpitLoading({ error }: { error: string | null }): JSX.Element | null {
  if (error) return <p className="cockpit-evidence-gap" role="alert">Evidence missing - cockpit payload unavailable: {error}</p>;
  return <p className="cockpit-evidence-gap">Loading cockpit evidence...</p>;
}

export function SafetyTopBar({ payload }: { payload: CockpitPayload }): JSX.Element {
  return (
    <section className="cockpit-topbar" data-testid="cockpit-topbar">
      <Metric label="Live trading" value={payload.live_gate_status} />
      <Metric label="Account mode" value={payload.account_mode} />
      <Metric label="Selected symbol" value={payload.selected_symbol} />
      <Metric label="Generated" value={payload.generated_at} />
    </section>
  );
}

export function Metric({ label, value, detail }: { label: string; value: unknown; detail?: string }): JSX.Element {
  return (
    <div className="cockpit-metric">
      <span>{label}</span>
      <strong className={statusClass(value)}>{valueText(value)}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

export function Panel({ id, title, children }: { id: string; title: string; children: ReactNode }): JSX.Element {
  return (
    <section className="cockpit-panel" id={id} data-testid={`cockpit-${id}`}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}

export function FreshnessBadge({ freshness }: { freshness: Freshness }): JSX.Element {
  return (
    <span className={statusClass(freshness.freshness_state)} title={freshness.source_pointer}>
      {freshness.freshness_state} / {freshness.mode}
    </span>
  );
}

export function MarketPulse({ payload }: { payload: CockpitPayload }): JSX.Element {
  return (
    <Panel id="market-pulse" title="Market Pulse">
      <div className="cockpit-analytics-grid">
        {payload.analytics_cards.map((card) => (
          <div className="cockpit-analytics-card" key={card.label}>
            <span>{card.label}</span>
            <strong>{card.value}</strong>
            <small>{card.detail}</small>
            <FreshnessBadge freshness={card.freshness} />
          </div>
        ))}
      </div>
      <div className="cockpit-market-table" role="table">
        <div className="cockpit-table-row cockpit-table-row--head" role="row">
          <span>Symbol</span><span>Price</span><span>1H / 24H</span><span>Funding</span><span>OI</span><span>Long/Short</span><span>Risk</span><span>Freshness</span>
        </div>
        {payload.market_rows.map((row) => (
          <div className="cockpit-table-row" role="row" key={row.symbol}>
            <span>{row.symbol}</span>
            <span>{row.price}</span>
            <span>{row.change_1h} / {row.change_24h}</span>
            <span>{row.funding_rate}</span>
            <span>{row.open_interest} ({row.oi_change_24h})</span>
            <span>{row.long_short_ratio}</span>
            <span className={statusClass(row.risk_state)}>{row.risk_state}</span>
            <FreshnessBadge freshness={row.freshness} />
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function ChartPanel({ candles, decisions, sourceType }: { candles: Candle[]; decisions: DecisionRow[]; sourceType?: string }): JSX.Element {
  const width = 760;
  const height = 260;
  const prices = candles.flatMap((c) => [c.high, c.low]);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const y = (price: number) => height - 24 - ((price - min) / (max - min || 1)) * (height - 48);
  const step = width / Math.max(candles.length, 1);
  return (
    <Panel id="charting-market-data" title="BTCUSDT Chart, Signals, And Risk Markers">
      <svg className="cockpit-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="BTCUSDT candlestick chart with risk markers">
        <rect x="0" y="0" width={width} height={height} rx="6" />
        {candles.map((candle, index) => {
          const x = index * step + step / 2;
          const open = y(candle.open);
          const close = y(candle.close);
          const high = y(candle.high);
          const low = y(candle.low);
          const bodyTop = Math.min(open, close);
          const bodyHeight = Math.max(Math.abs(close - open), 2);
          const up = candle.close >= candle.open;
          return (
            <g key={candle.time}>
              <line x1={x} x2={x} y1={high} y2={low} className={up ? 'candle-up' : 'candle-down'} />
              <rect x={x - 5} y={bodyTop} width="10" height={bodyHeight} className={up ? 'candle-up' : 'candle-down'} />
              <rect x={x - 5} y={height - 18 - candle.volume / 900} width="10" height={candle.volume / 900} className="volume-bar" />
            </g>
          );
        })}
        {decisions.slice(0, 3).map((decision, index) => (
          <g key={decision.id}>
            <circle cx={80 + index * 180} cy={42 + index * 22} r="7" className={decision.risk_reason.includes('blocked') ? 'risk-marker' : 'signal-marker'} />
            <text x={94 + index * 180} y={47 + index * 22}>{decision.symbol} {decision.risk_reason}</text>
          </g>
        ))}
      </svg>
      <p className="cockpit-evidence-note">
        {sourceType === 'READONLY_MARKET_FEED'
          ? 'READONLY_MARKET_FEED: chart uses Binance USD-M public GET-only market data. It cannot place orders.'
          : 'STATIC_PROOF_FIXTURE: chart uses deterministic static proof candles until Binance USD-M `/fapi/v1/klines` read-only market data is wired. It cannot place orders.'}
      </p>
    </Panel>
  );
}

export function DecisionDrawers({ rows }: { rows: DecisionRow[] }): JSX.Element {
  return (
    <Panel id="decision-explainability" title="Decision Explainability Drawers">
      {rows.map((row) => (
        <details className="cockpit-decision-drawer" key={row.id} open={row.symbol === 'LABUSDT'}>
          <summary>
            <span>{row.symbol}</span>
            <span>{row.prediction_id}</span>
            <span className={statusClass(row.risk_reason)}>{row.risk_reason}</span>
          </summary>
          <div className="cockpit-lineage-grid">
            {([
              ['feature_snapshot_id', row.feature_snapshot_id],
              ['signal_id', row.signal_id],
              ['orchestrator_decision_id', row.orchestrator_decision_id],
              ['risk_decision_id', row.risk_decision_id],
              ['execution_intent_id', row.execution_intent_id],
              ['model/checkpoint', row.model_checkpoint],
              ['raw/calibrated/delta', `${row.confidence_raw} / ${row.confidence_calibrated} / ${row.confidence_delta}`],
              ['source freshness', row.source_freshness_by_ingestor],
              ['signal reason', row.signal_reason],
              ['orchestrator reason', row.orchestrator_reason],
              ['risk reason', row.risk_reason],
              ['result', row.result],
            ] satisfies Array<[string, unknown]>).map(([label, value]) => (
              <div key={label}>
                <span>{label}</span>
                <strong>{valueText(value)}</strong>
              </div>
            ))}
          </div>
          <div className="cockpit-mini-grid">
            <MiniList title="Top positive" items={row.top_positive} />
            <MiniList title="Top negative" items={row.top_negative} />
            <MiniList title="Stale flags" items={row.stale_flags} />
            <MiniList title="Missing flags" items={row.missing_flags.length ? row.missing_flags : ['Evidence missing - cannot explain without guessing']} />
          </div>
        </details>
      ))}
    </Panel>
  );
}

export function ExchangeManager({ rows }: { rows: ExchangeConnector[] }): JSX.Element {
  return (
    <Panel id="exchange-manager" title="Exchange Manager - Read Only Linking">
      <div className="cockpit-card-grid">
        {rows.map((row) => (
          <div className="cockpit-exchange-card" key={row.exchange}>
            <h3>{row.exchange}</h3>
            <Metric label="Status" value={row.status} />
            <Metric label="Read-only key" value={row.read_only_key_status} />
            <Metric label="Trade permission" value={row.trade_permission} />
            <Metric label="Order capability" value={row.order_capability} />
            <Metric label="IP restriction" value={row.ip_restriction_status} />
            <FreshnessBadge freshness={row.freshness} />
            <p>{row.notes}</p>
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function MonitorTable({ rows }: { rows: MonitorRow[] }): JSX.Element {
  return (
    <Panel id="monitor-center" title="Monitor Center">
      <div className="cockpit-market-table" role="table">
        <div className="cockpit-table-row cockpit-table-row--head" role="row">
          <span>Script</span><span>Status</span><span>Owner</span><span>Last success</span><span>Metrics</span><span>Redis</span><span>Logs</span><span>Processes</span><span>Alerts</span>
        </div>
        {rows.map((row) => (
          <div className="cockpit-table-row" role="row" key={row.script_path}>
            <span>{row.script_path}</span>
            <span className={statusClass(row.status)}>{row.classification} / {row.status}</span>
            <span>{row.owner}</span>
            <span>{row.last_success}</span>
            <span>{valueText(row.metrics_emitted)}</span>
            <span>{valueText(row.redis_keys_watched)}</span>
            <span>{valueText(row.logs_watched)}</span>
            <span>{valueText(row.processes_watched)}</span>
            <span>{valueText(row.alerts)}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function ConfigTable({ rows }: { rows: SettingRow[] }): JSX.Element {
  return (
    <Panel id="config-admin" title="Config Admin - Safety Classified Settings">
      <div className="cockpit-market-table" role="table">
        <div className="cockpit-table-row cockpit-table-row--head" role="row">
          <span>Setting</span><span>Value</span><span>Classification</span><span>Reason</span>
        </div>
        {rows.map((row) => (
          <div className="cockpit-table-row" role="row" key={row.name}>
            <span>{row.name}</span>
            <span>{row.value}</span>
            <span className={statusClass(row.classification)}>{row.classification}</span>
            <span>{row.reason}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function QuarantinePanel({ payload }: { payload: QuarantinePayload | null }): JSX.Element {
  const rows = payload?.ownership_rows ?? [];
  return (
    <Panel id="external-manual-position-quarantine" title="External / Manual Position Quarantine">
      <div className="cockpit-analytics-grid">
        <Metric label="Gate" value={payload?.go_no_go ?? 'Evidence missing'} />
        <Metric label="Quarantined" value={payload?.summary?.quarantined_count ?? 'Evidence missing'} />
        <Metric label="Manual external" value={payload?.summary?.manual_external_count ?? 'Evidence missing'} />
        <Metric label="Duplicate accounting" value={payload?.summary?.duplicate_accounting_candidate_count ?? 'Evidence missing'} />
      </div>
      <div className="cockpit-market-table" role="table">
        <div className="cockpit-table-row cockpit-table-row--head" role="row">
          <span>Symbol</span><span>Ownership</span><span>Reason</span><span>Missing</span><span>Allowed</span><span>Blocked</span>
        </div>
        {rows.map((row) => (
          <div className="cockpit-table-row" role="row" key={valueText(row.evidence_id)}>
            <span>{valueText(row.symbol)}</span>
            <span className={statusClass(row.ownership_classification)}>{valueText(row.ownership_classification)}</span>
            <span>{valueText(row.quarantine_reason)}</span>
            <span>{valueText(row.missing_attribution_fields)}</span>
            <span>{valueText(row.allowed_actions)}</span>
            <span>{valueText(row.blocked_actions)}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function SystemAtlasPanel({ payload }: { payload: SystemAtlasPayload | null }): JSX.Element {
  if (!payload) {
    return (
      <Panel id="system-atlas-runtime-coverage" title="System Atlas / Runtime Coverage">
        <p className="cockpit-evidence-gap">Evidence missing - system atlas payload unavailable.</p>
      </Panel>
    );
  }
  return (
    <Panel id="system-atlas-runtime-coverage" title="System Atlas / Runtime Coverage">
      <div className="cockpit-analytics-grid">
        <Metric label="Gate" value={payload.go_no_go} />
        <Metric label="Files" value={payload.counts.files} />
        <Metric label="Scripts" value={payload.counts.scripts} />
        <Metric label="Unsafe unknown" value={payload.counts.unsafe_unknown} />
        <Metric label="Exchange paths" value={payload.counts.unmapped_exchange_action_paths} />
        <Metric label="Redis writers" value={payload.counts.redis_writer_paths} />
        <Metric label="Runtime unmapped" value={payload.counts.unmapped_runtime_processes} />
        <Metric label="12h monitor" value={payload.runtime_monitor.status} />
      </div>
      <div className="cockpit-card-grid">
        {payload.top_gaps.slice(0, 8).map((gap) => (
          <div className="cockpit-evidence-gap" key={gap}>{gap}</div>
        ))}
      </div>
    </Panel>
  );
}

export function SystemAtlasGapRemediationPanel({ payload }: { payload: SystemAtlasGapRemediationPayload | null }): JSX.Element {
  if (!payload) {
    return (
      <Panel id="system-atlas-gap-remediation" title="Phase 3B System Atlas Gap Remediation">
        <p className="cockpit-evidence-gap">Evidence missing - Phase 3B remediation payload unavailable.</p>
      </Panel>
    );
  }
  const blockers = [
    ...payload.remaining_blockers.unsafe_unknown.map((row) => `unsafe_unknown: ${row}`),
    ...payload.remaining_blockers.exchange.map((row) => `exchange: ${row}`),
    ...payload.remaining_blockers.redis.map((row) => `redis: ${row}`),
    ...payload.remaining_blockers.runtime.map((row) => `runtime: ${row}`),
  ];
  return (
    <Panel id="system-atlas-gap-remediation" title="Phase 3B System Atlas Gap Remediation">
      <div className="cockpit-analytics-grid">
        <Metric label="Gate" value={payload.go_no_go} />
        <Metric label="Codex" value={payload.codex_go_no_go} />
        <Metric label="Unsafe unknown remaining" value={payload.counts.unsafe_unknown_remaining} />
        <Metric label="Exchange unmapped" value={payload.counts.unmapped_exchange_action_paths} />
        <Metric label="Redis writers unmapped" value={payload.counts.unmapped_redis_writer_paths} />
        <Metric label="Unknown bot-like processes" value={payload.counts.unknown_bot_like_process_count} />
        <Metric label="Bot-scope runtime unmapped" value={payload.counts.unmapped_runtime_processes_in_bot_scope} />
        <Metric label="Non-bot host processes" value={payload.counts.host_or_non_bot_processes} />
      </div>
      <div className="cockpit-card-grid">
        {blockers.slice(0, 16).map((gap) => (
          <div className="cockpit-evidence-gap" key={gap}>{gap}</div>
        ))}
        {blockers.length === 0 ? <div className="cockpit-evidence-gap">No Phase 3B blockers recorded.</div> : null}
      </div>
    </Panel>
  );
}

export function Phase3cRuntimeMonitorPanel({ payload }: { payload: Phase3cRuntimeMonitorPayload | null }): JSX.Element {
  if (!payload) {
    return (
      <Panel id="phase3c-runtime-monitor-verification" title="Phase 3C Runtime Monitor Verification">
        <p className="cockpit-evidence-gap">Evidence missing - Phase 3C runtime monitor payload unavailable.</p>
      </Panel>
    );
  }
  return (
    <Panel id="phase3c-runtime-monitor-verification" title="Phase 3C Runtime Monitor Verification">
      <div className="cockpit-analytics-grid">
        <Metric label="Gate" value={payload.go_no_go} />
        <Metric label="Codex" value={payload.codex_go_no_go} />
        <Metric label="Next milestone" value={payload.next_safe_milestone} />
        <Metric label="Duration hours" value={payload.counts.duration_hours} />
        <Metric label="Snapshots" value={payload.counts.snapshot_count} />
        <Metric label="Trainer metrics" value={payload.counts.trainer_metric_count} />
        <Metric label="Redis max memory" value={`${payload.counts.redis_memory_max_pct}%`} />
        <Metric label="Blocking gaps" value={payload.counts.blocking_gap_count} />
      </div>
      <div className="cockpit-card-grid">
        <div className="cockpit-exchange-card">
          <h3>Runtime Window</h3>
          <p>First snapshot: {valueText(payload.latest.first_snapshot_ts)}</p>
          <p>Last snapshot: {valueText(payload.latest.last_snapshot_ts)}</p>
          <p>Trainer latest: {valueText(payload.latest.latest_trainer_status)}</p>
          <p>Publish surface: {valueText(payload.latest.publish_surface_liveness)}</p>
        </div>
        <div className="cockpit-exchange-card">
          <h3>Lineage Snapshot</h3>
          <p>Executed analysis: {valueText(payload.latest.executed_analysis)}</p>
          <p>Attribution: {valueText(payload.latest.attribution_completeness)}</p>
        </div>
        {payload.gaps.slice(0, 12).map((gap) => (
          <div className="cockpit-evidence-gap" key={`${gap.gap}-${gap.evidence}`}>
            {gap.severity}: {gap.gap} ({gap.evidence})
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function RedisMemoryPressurePanel({ payload }: { payload: RedisMemoryPressurePayload | null }): JSX.Element {
  if (!payload) {
    return (
      <Panel id="redis-memory-pressure-remediation" title="Redis Memory Pressure Remediation">
        <p className="cockpit-evidence-gap">Evidence missing - Redis memory pressure remediation payload unavailable.</p>
      </Panel>
    );
  }
  return (
    <Panel id="redis-memory-pressure-remediation" title="Redis Memory Pressure Remediation">
      <div className="cockpit-analytics-grid">
        <Metric label="Gate" value={payload.go_no_go} />
        <Metric label="Codex" value={payload.codex_go_no_go} />
        <Metric label="Next milestone" value={payload.next_safe_milestone} />
        <Metric label="Used memory" value={payload.redis_info.used_memory_human} />
        <Metric label="Max memory" value={payload.redis_info.maxmemory_human} />
        <Metric label="Policy" value={payload.redis_info.maxmemory_policy} />
        <Metric label="Keys scanned" value={payload.counts.keys_scanned} />
        <Metric label="Dry-run actions" value={payload.counts.dry_run_action_count} />
      </div>
      <div className="cockpit-card-grid">
        <div className="cockpit-evidence-gap">
          Redis mutation requires explicit human approval. This plan does not execute DEL, XDEL, XTRIM, SET, HSET, XADD, FLUSHALL, or FLUSHDB.
        </div>
        {payload.top_consumers.slice(0, 8).map((row) => (
          <div className="cockpit-exchange-card" key={valueText(row.key)}>
            <h3>{valueText(row.key)}</h3>
            <p>Type: {valueText(row.type)} / Namespace: {valueText(row.namespace)}</p>
            <p>Memory: {valueText(row.memory_mb)} MB / Stream length: {valueText(row.stream_length)}</p>
            <p>Criticality: {valueText(row.criticality)}</p>
          </div>
        ))}
        {payload.dry_run_actions.slice(0, 8).map((row) => (
          <div className="cockpit-evidence-gap" key={`${valueText(row.key)}-${valueText(row.proposed_action)}`}>
            {valueText(row.proposed_action)}: {valueText(row.key)} saves approx {valueText(row.estimated_memory_reduction_mb)} MB; approval: {valueText(row.required_approval)}
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function RedisHumanApprovalPanel({ payload }: { payload: RedisHumanApprovalPayload | null }): JSX.Element {
  if (!payload) {
    return (
      <Panel id="redis-human-approval-packet" title="Redis Export And Human Approval Packet">
        <p className="cockpit-evidence-gap">Evidence missing - Redis human approval payload unavailable.</p>
      </Panel>
    );
  }
  return (
    <Panel id="redis-human-approval-packet" title="Redis Export And Human Approval Packet">
      <div className="cockpit-analytics-grid">
        <Metric label="Gate" value={payload.go_no_go} />
        <Metric label="Codex" value={payload.codex_go_no_go} />
        <Metric label="Next milestone" value={payload.next_safe_milestone} />
        <Metric label="Target key" value={payload.target_key} />
        <Metric label="Memory" value={`${payload.preflight_summary.memory_usage_mb} MB`} />
        <Metric label="XLEN" value={payload.preflight_summary.xlen} />
        <Metric label="Export complete" value={payload.export.complete ? 'yes' : 'no'} />
        <Metric label="Consumer safety" value={payload.consumer_safety.status} />
      </div>
      <div className="cockpit-card-grid">
        <div className="cockpit-evidence-gap">
          Human approval required before any Redis mutation. Proposed commands are documented for review only and were not executed.
        </div>
        <div className="cockpit-exchange-card">
          <h3>Export Proof</h3>
          <p>Mode: {payload.export.mode}</p>
          <p>Entries exported: {payload.export.exported_entries} of {payload.export.stream_length}</p>
          <p>Coverage: {payload.export.coverage_ratio}</p>
          <p>{payload.export.full_export_blocker}</p>
        </div>
        <div className="cockpit-exchange-card">
          <h3>Consumer Safety</h3>
          <p>{payload.consumer_safety.reason}</p>
          <p>Pending total: {payload.consumer_safety.pending_total}</p>
        </div>
        <div className="cockpit-evidence-gap">
          DO NOT RUN: {payload.proposed_trim.preferred_command_do_not_run}
        </div>
        <div className="cockpit-evidence-gap">
          Alternate DO NOT RUN: {payload.proposed_trim.alternate_command_do_not_run}
        </div>
      </div>
    </Panel>
  );
}

export function RedisExportCapacityPanel({ payload }: { payload: RedisExportCapacityPayload | null }): JSX.Element {
  if (!payload) {
    return (
      <Panel id="redis-export-capacity-remediation" title="Redis Export Capacity Remediation">
        <p className="cockpit-evidence-gap">Evidence missing - Redis export capacity payload unavailable.</p>
      </Panel>
    );
  }
  return (
    <Panel id="redis-export-capacity-remediation" title="Redis Export Capacity Remediation">
      <div className="cockpit-analytics-grid">
        <Metric label="Gate" value={payload.go_no_go} />
        <Metric label="Codex" value={payload.codex_go_no_go} />
        <Metric label="Next milestone" value={payload.next_safe_milestone} />
        <Metric label="Target key" value={payload.target_key} />
        <Metric label="Stream length" value={payload.stream.xlen} />
        <Metric label="Best entries/sec" value={payload.best_benchmark.entries_per_second} />
        <Metric label="Runtime estimate" value={`${payload.export_estimate.estimated_runtime_hours} h`} />
        <Metric label="Compressed estimate" value={`${payload.export_estimate.estimated_compressed_gib} GiB`} />
      </div>
      <div className="cockpit-card-grid">
        <div className="cockpit-evidence-gap">
          Full export appears feasible from bounded benchmark, but still requires human approval before running. No Redis trim or mutation has occurred.
        </div>
        <div className="cockpit-exchange-card">
          <h3>Benchmark</h3>
          <p>Batch: {valueText(payload.best_benchmark.batch_size)}</p>
          <p>Elapsed: {valueText(payload.best_benchmark.elapsed_seconds)}s</p>
          <p>Compression ratio: {valueText(payload.best_benchmark.compression_ratio)}</p>
        </div>
        <div className="cockpit-exchange-card">
          <h3>Safety</h3>
          <p>Consumer safety: {payload.consumer_safety.status}</p>
          <p>Pending: {payload.consumer_safety.pending_total}</p>
          <p>{payload.snapshot_recommendation}</p>
        </div>
      </div>
    </Panel>
  );
}

export function RedisFullExportPanel({ payload }: { payload: RedisFullExportPayload | null }): JSX.Element {
  if (!payload) {
    return (
      <Panel id="redis-liquidations-full-export" title="Redis Liquidations Full Export">
        <p className="cockpit-evidence-gap">Evidence missing - Redis full export payload unavailable.</p>
      </Panel>
    );
  }
  return (
    <Panel id="redis-liquidations-full-export" title="Redis Liquidations Full Export">
      <div className="cockpit-analytics-grid">
        <Metric label="Gate" value={payload.go_no_go} />
        <Metric label="Codex" value={payload.codex_go_no_go} />
        <Metric label="Next milestone" value={payload.next_safe_milestone} />
        <Metric label="Target key" value={payload.target_key} />
        <Metric label="Exported entries" value={payload.exported_count} />
        <Metric label="Chunks" value={payload.chunk_count} />
        <Metric label="Compressed size" value={`${payload.compressed_total_gib} GiB`} />
        <Metric label="Integrity" value={payload.integrity_status} />
      </div>
      <div className="cockpit-card-grid">
        <div className="cockpit-evidence-gap">
          Full export verified. Redis trim is still not approved and no Redis mutation has occurred.
        </div>
        <div className="cockpit-exchange-card">
          <h3>Export Anchor</h3>
          <p>Pre-export length: {payload.pre_export_xlen}</p>
          <p>Duration: {payload.duration_seconds}s</p>
          <p>Consumer safety: {payload.consumer_safety_status}</p>
          <p>Live gate: {payload.live_gate_status}</p>
        </div>
      </div>
    </Panel>
  );
}

function MiniList({ title, items }: { title: string; items: string[] }): JSX.Element {
  return (
    <div className="cockpit-mini-list">
      <h3>{title}</h3>
      {items.map((item) => <span key={item}>{item}</span>)}
    </div>
  );
}
