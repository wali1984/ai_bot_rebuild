import { DANGEROUS_CONTROLS, type DangerousControlId } from '../../constants/dangerousControls';
import { RequiresApprovalBadge } from './RequiresApprovalBadge';

interface Props {
  controlIds: ReadonlyArray<DangerousControlId>;
}

export function DangerousControlPanel({ controlIds }: Props): JSX.Element | null {
  if (controlIds.length === 0) return null;
  return (
    <section className="dangerous-control-panel" data-testid="dangerous-control-panel">
      <h2>Dangerous controls (default-deny)</h2>
      <ul>
        {controlIds.map((id) => {
          const ctrl = DANGEROUS_CONTROLS[id];
          return (
            <li key={id} data-testid={`dangerous-control-${id}`}>
              <button
                type="button"
                disabled
                aria-disabled="true"
                data-control-id={id}
                data-control-level={ctrl.level}
                className="dangerous-control-button"
              >
                {ctrl.label}
              </button>
              <RequiresApprovalBadge controlId={id} />
            </li>
          );
        })}
      </ul>
    </section>
  );
}
