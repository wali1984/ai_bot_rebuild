import type { TradeTerminalState } from '../../hooks/useTradeTerminal';
import { formatPercent, formatPrice, formatTime } from '../../lib/tradeFormatters';
import { tradeCopy } from '../../lib/tradeCopy';

function auditEventCopy(raw: unknown): string {
  switch (String(raw ?? '').toLowerCase()) {
    case 'paper_order_staged_local':
      return 'Order staged';
    case 'paper_order_canceled_local':
      return 'Order canceled';
    case 'paper_order_filled_local':
      return 'Order filled';
    case 'stage':
      return 'Staging event';
    case 'cancel':
      return 'Cancel event';
    case 'fill':
      return 'Fill event';
    default:
      return 'Execution audit event';
  }
}

export function SignalEvidencePanel({ state }: { state: TradeTerminalState }): JSX.Element {
  const auditEvents = state.activity.auditEvents.slice(0, 4);
  const auditPolicy = state.activity.auditPolicy;
  const auditLedger = state.activity.auditLedger;
  const auditStatusCopy = [
    auditPolicy?.tamper_evident ? 'Tamper-evident' : 'Local audit',
    auditPolicy?.production_durable_store ? 'Durable store' : 'File-backed',
    auditLedger?.append_only_local_file ? 'Append-only ledger' : 'Local ledger',
  ].join(' · ');

  // Entry: signal entry price if present, else current market last price as reference
  const signalEntry = typeof state.signal.entry === 'number' && Number.isFinite(state.signal.entry) ? state.signal.entry : null;
  const entryPrice = signalEntry ?? state.market.lastPrice;
  const entryIsMarketProxy = signalEntry == null && state.market.lastPrice != null;

  // Optional levels: show formatted price if available, else '—'
  const optionalPrice = (v: unknown): string => {
    const n = typeof v === 'number' && Number.isFinite(v) ? v : null;
    return n != null ? formatPrice(n) : '—';
  };

  return (
    <div className="trade-evidence-panel" data-testid="signal-evidence-panel">
      <div className="trade-evidence-panel__summary">
        <div><span>Direction</span><strong>{tradeCopy(state.signal.direction)}</strong></div>
        <div><span>Executable confidence</span><strong>{formatPercent(state.signal.executableConfidence)}</strong></div>
        <div><span>Selected confidence</span><strong>{formatPercent(state.signal.selectedConfidence)}</strong></div>
        <div><span>Strategy</span><strong>{tradeCopy(state.signal.strategy)}</strong></div>
        <div><span>Model</span><strong>{tradeCopy(state.signal.modelVersion)}</strong></div>
        <div><span>Risk decision</span><strong>{tradeCopy(state.signal.riskDecision)}</strong></div>
        <div><span>Confidence label</span><strong>{tradeCopy(state.signal.confidenceLabel)}</strong></div>
        <div><span>Freshness</span><strong title={state.signal.source}>{tradeCopy(state.signal.freshness)}</strong></div>
      </div>
      <div className="trade-evidence-panel__levels">
        <span>
          Entry{entryIsMarketProxy ? <em style={{ fontSize: 10, marginLeft: 4, opacity: 0.6 }}>(last price)</em> : null}{' '}
          <strong>{formatPrice(entryPrice)}</strong>
        </span>
        <span>Target 1 <strong>{optionalPrice(state.signal.target1)}</strong></span>
        <span>Target 2 <strong>{optionalPrice(state.signal.target2)}</strong></span>
        <span>Target 3 <strong>{optionalPrice(state.signal.target3)}</strong></span>
        <span>Stop <strong>{optionalPrice(state.signal.stop)}</strong></span>
        <span>Invalidation <strong>{optionalPrice(state.signal.invalidation)}</strong></span>
      </div>
      <details className="trade-evidence-panel__drawer">
        <summary>Evidence details</summary>
        <p>Entry shows the signal-provided price when available, otherwise the current market last price. Target 2/3, Stop, and Invalidation are optional — shown when included in the signal.</p>
      </details>
      <div className="trade-evidence-panel__audit" data-testid="paper-audit-events">
        <h4>Execution audit events</h4>
        <p className="trade-evidence-panel__audit-policy">{auditStatusCopy}</p>
        {auditEvents.length ? (
          <div className="trade-evidence-panel__audit-list">
            {auditEvents.map((event, index) => (
              <div className="trade-evidence-panel__audit-row" key={`${String(event.audit_id ?? event.id ?? 'audit')}-${index}`}>
                <span>{formatTime(String(event.created_at ?? event.time ?? ''))}</span>
                <strong>{auditEventCopy(event.audit_event ?? event.action)}</strong>
                <em>{tradeCopy(String(event.source ?? 'Execution repository audit'))}</em>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ padding: '8px 0', color: 'var(--text-muted)', fontSize: 12, fontFamily: 'var(--font-mono)' }}>
            No execution audit events in the current stream window.
          </div>
        )}
      </div>
    </div>
  );
}
