export interface LineageBlock {
  prediction_id?: string | null;
  signal_id?: string | null;
  decision_id?: string | null;
  risk_decision_id?: string | null;
  intent_id?: string | null;
  feature_snapshot_id?: string | null;
  model_version?: string | null;
  checkpoint_id?: string | null;
  config_version?: string | null;
  lineage_gap_reason?: string | null;
}

interface Props {
  block: LineageBlock;
}

const FIELDS: ReadonlyArray<{ key: keyof LineageBlock; label: string; entityRoute?: string }> = [
  { key: 'prediction_id', label: 'Prediction', entityRoute: '/admin/trainer-prediction-monitor' },
  { key: 'signal_id', label: 'Signal', entityRoute: '/admin/signals' },
  { key: 'decision_id', label: 'Decision', entityRoute: '/admin/orchestrator-admin' },
  { key: 'risk_decision_id', label: 'Risk decision', entityRoute: '/admin/risk-control' },
  { key: 'intent_id', label: 'Execution intent', entityRoute: '/admin/executions' },
  { key: 'feature_snapshot_id', label: 'Feature snapshot' },
  { key: 'model_version', label: 'Model version' },
  { key: 'checkpoint_id', label: 'Checkpoint' },
  { key: 'config_version', label: 'Config version' },
];

export function LineageBlockView({ block }: Props): JSX.Element {
  return (
    <section className="lineage-block" data-testid="lineage-block">
      <h3>Lineage chain</h3>
      <dl>
        {FIELDS.map(({ key, label, entityRoute }) => {
          const value = block[key];
          if (value == null) {
            return (
              <div key={key} data-testid={`lineage-${key}`} data-state="missing">
                <dt>{label}</dt>
                <dd>
                  <em>missing</em>
                  {block.lineage_gap_reason ? (
                    <span className="lineage-block__gap"> — gap_reason: {block.lineage_gap_reason}</span>
                  ) : null}
                </dd>
              </div>
            );
          }
          return (
            <div key={key} data-testid={`lineage-${key}`} data-state="present">
              <dt>{label}</dt>
              <dd>
                {entityRoute ? (
                  <a href={`${entityRoute}?id=${encodeURIComponent(String(value))}`}>{String(value)}</a>
                ) : (
                  <code>{String(value)}</code>
                )}
              </dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}
