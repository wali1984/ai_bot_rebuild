import { useState } from 'react';
import { DANGEROUS_CONTROLS, type DangerousControlId } from '../../constants/dangerousControls';

interface Props {
  controlId: DangerousControlId;
}

export function RequiresApprovalBadge({ controlId }: Props): JSX.Element {
  const ctrl = DANGEROUS_CONTROLS[controlId];
  const [open, setOpen] = useState(false);
  return (
    <span className="requires-approval-badge" data-testid={`requires-approval-${controlId}`}>
      <button
        type="button"
        className={`badge badge--${ctrl.level.toLowerCase()}`}
        aria-label={`Requires ${ctrl.level} approval to ${ctrl.label.toLowerCase()}`}
        onClick={() => setOpen((v) => !v)}
      >
        Requires {ctrl.level} approval
      </button>
      {open ? (
        <div role="dialog" aria-modal="false" className="approval-modal" data-testid={`approval-modal-${controlId}`}>
          <p>{ctrl.rationale}</p>
          <p>
            Submitting this request would emit <code>governance.approvals.create</code>.
            The mutation never fires from the GUI without the approval token returned by the backend.
          </p>
          <button type="button" onClick={() => setOpen(false)}>Close</button>
        </div>
      ) : null}
    </span>
  );
}
