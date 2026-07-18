import meta from './meta';
import rbac from './rbac';
import route from './route';
import { Panel } from '../cockpitComponents';
import { statusClass, valueText } from '../cockpitData';
import { useCoinankMarketIntelligencePayload, usePaperOnlineRuntimePayload } from '../operatorTruthData';
import { CoinankMarketIntelligencePanel, PaperOnlineRuntimeStatusPanel } from '../operatorTruthComponents';
import { usePayloadFile } from '../../hooks/usePayloadFile';

interface ScriptRegistryPayload {
  generated_at: string;
  count: number;
  scripts: Array<{ path: string; classification: string; risk_level: string; redis_writes: string[]; exchange_api_calls: string[]; v2_action: string }>;
}

export default function ScriptRegistryPage(): JSX.Element {
  const { data: payload, error } = usePayloadFile<ScriptRegistryPayload>(
    '/system_atlas_runtime_coverage/latest/SCRIPT_REGISTRY.json',
    30_000,
  );
  const { payload: paperRuntime } = usePaperOnlineRuntimePayload();
  const { payload: coinankPayload, error: coinankError } = useCoinankMarketIntelligencePayload();

  return (
    <article className="enterprise-cockpit-page" data-testid="page-script-registry" data-page-id={meta.id} data-page-path={route.path} data-page-min-role={rbac.minRole} style={{ background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)' }}>
      <header className="enterprise-cockpit-hero">
        <div>
          <p className="cockpit-kicker">Script Registry</p>
          <h1>{meta.title}</h1>
          <p>{meta.description}</p>
        </div>
      </header>
      <PaperOnlineRuntimeStatusPanel payload={paperRuntime} />
      {!payload ? (
        <p className="cockpit-evidence-gap">{error ?? 'Connecting script registry evidence stream...'}</p>
      ) : (
        <>
          <CoinankMarketIntelligencePanel payload={coinankPayload} error={coinankError} context="Script Registry" />
          <Panel id="script-registry-table" title={`Mapped Scripts (${payload.count})`}>
            <div className="cockpit-market-table" role="table">
              <div className="cockpit-table-row cockpit-table-row--head" role="row">
                <span>Path</span><span>Classification</span><span>Risk</span><span>Redis writes</span><span>Exchange actions</span><span>V2 action</span>
              </div>
              {payload.scripts.slice(0, 120).map((row) => (
                <div className="cockpit-table-row" role="row" key={row.path}>
                  <span>{row.path}</span>
                  <span className={statusClass(row.classification)}>{row.classification}</span>
                  <span className={statusClass(row.risk_level)}>{row.risk_level}</span>
                  <span>{valueText(row.redis_writes)}</span>
                  <span>{valueText(row.exchange_api_calls)}</span>
                  <span>{row.v2_action}</span>
                </div>
              ))}
            </div>
          </Panel>
        </>
      )}
    </article>
  );
}
