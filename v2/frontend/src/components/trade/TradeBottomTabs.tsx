import { useEffect, useState } from 'react';
import type { TradeTerminalState } from '../../hooks/useTradeTerminal';
import { TradePanel } from './TradeShared';
import { ExecutionsTable } from './ExecutionsTable';
import { OpenOrdersTable } from './OpenOrdersTable';
import { PositionsTable } from './PositionsTable';
import { SignalEvidencePanel } from './SignalEvidencePanel';
import { TradeSystemPanel } from './TradeSystemPanel';
import { HourlyMonitorPanel } from './HourlyMonitorPanel';

const TABS = ['Positions', 'Open Orders', 'Executions', 'Order History', 'Signal Evidence', 'System', 'Monitor'] as const;
type Tab = (typeof TABS)[number];

export function TradeBottomTabs({
  state,
  mobileFocus,
  initialTab = 'Positions',
}: {
  state: TradeTerminalState;
  mobileFocus?: 'positions' | 'evidence';
  initialTab?: Tab;
}): JSX.Element {
  const [active, setActive] = useState<Tab>(initialTab);

  useEffect(() => {
    if (mobileFocus === 'positions') setActive('Positions');
    if (mobileFocus === 'evidence') setActive('Signal Evidence');
  }, [mobileFocus]);

  useEffect(() => {
    if (!mobileFocus) setActive(initialTab);
  }, [initialTab, mobileFocus]);

  return (
    <div className="trade-mobile-panel" data-mobile-panel={active === 'Signal Evidence' ? 'evidence' : 'positions'}>
      <TradePanel title="Account Panel" kicker="Execution activity" testId="trade-bottom-tabs">
        <div className="trade-tabs" role="tablist" aria-label="Trade account tabs">
          {TABS.map((tab) => (
            <button
              type="button"
              role="tab"
              aria-selected={active === tab}
              className={active === tab ? 'is-active' : ''}
              onClick={() => setActive(tab)}
              key={tab}
            >
              {tab}
            </button>
          ))}
        </div>
        <div className="trade-tabs__panel" role="tabpanel">
          {/* Keep all panels mounted (display:none) to prevent useRealtimeResource from resetting on tab switch */}
          <div style={{ display: active === 'Positions' ? undefined : 'none' }}><PositionsTable state={state} /></div>
          <div style={{ display: active === 'Open Orders' ? undefined : 'none' }}><OpenOrdersTable state={state} /></div>
          <div style={{ display: active === 'Executions' ? undefined : 'none' }}><ExecutionsTable state={state} /></div>
          <div style={{ display: active === 'Order History' ? undefined : 'none' }}><OpenOrdersTable state={state} history /></div>
          <div style={{ display: active === 'Signal Evidence' ? undefined : 'none' }}><SignalEvidencePanel state={state} /></div>
          <div style={{ display: active === 'System' ? undefined : 'none' }}><TradeSystemPanel state={state} /></div>
          <div style={{ display: active === 'Monitor' ? undefined : 'none' }}><HourlyMonitorPanel /></div>
        </div>
      </TradePanel>
    </div>
  );
}
