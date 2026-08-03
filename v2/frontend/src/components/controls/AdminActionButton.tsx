import React, { useState } from 'react';
import { ControlConfirmationDialog } from './ControlConfirmationDialog';

type Severity = 'normal' | 'warning' | 'critical';

interface AdminActionButtonProps {
  label: string;
  onClick: () => void;
  severity?: Severity;
  disabled?: boolean;
  requiresConfirmation?: boolean;
  confirmationTitle?: string;
  confirmationDesc?: string;
}

const severityStyles: Record<Severity, { color: string; border: string; bg: string; hoverBg: string }> = {
  normal: {
    color: 'var(--text-primary)',
    border: 'var(--border)',
    bg: 'var(--bg-elevated)',
    hoverBg: 'var(--bg-hover)',
  },
  warning: {
    color: 'var(--warn)',
    border: 'var(--warn)',
    bg: 'color-mix(in oklch, var(--warn) 10%, transparent)',
    hoverBg: 'color-mix(in oklch, var(--warn) 18%, transparent)',
  },
  critical: {
    color: 'var(--error)',
    border: 'var(--error)',
    bg: 'color-mix(in oklch, var(--error) 10%, transparent)',
    hoverBg: 'color-mix(in oklch, var(--error) 18%, transparent)',
  },
};

/**
 * Admin action button with optional confirmation dialog.
 * LIVE TRADING: BLOCKED. Must not be wired to any live exchange action.
 */
export const AdminActionButton: React.FC<AdminActionButtonProps> = ({
  label,
  onClick,
  severity = 'normal',
  disabled = false,
  requiresConfirmation = false,
  confirmationTitle,
  confirmationDesc,
}) => {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [isHovered, setIsHovered] = useState(false);
  const sty = severityStyles[severity];

  const dialogSeverity: 'warning' | 'critical' =
    severity === 'critical' ? 'critical' : 'warning';

  function handleClick() {
    if (disabled) return;
    if (requiresConfirmation) {
      setDialogOpen(true);
    } else {
      onClick();
    }
  }

  async function handleConfirm(_reason: string) {
    setDialogOpen(false);
    onClick();
  }

  return (
    <>
      <button
        data-testid="admin-action-button"
        onClick={handleClick}
        disabled={disabled}
        aria-disabled={disabled}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '6px',
          padding: '8px 16px',
          background: disabled
            ? 'var(--bg-elevated)'
            : isHovered
            ? sty.hoverBg
            : sty.bg,
          border: `1px solid ${disabled ? 'var(--border)' : sty.border}`,
          borderRadius: 'var(--radius-sm)',
          color: disabled ? 'var(--text-muted)' : sty.color,
          fontSize: '13px',
          fontWeight: 600,
          fontFamily: 'var(--font-sans)',
          cursor: disabled ? 'not-allowed' : 'pointer',
          opacity: disabled ? 0.55 : 1,
          transition: 'background var(--ease-fast), border-color var(--ease-fast)',
        }}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
      >
        {severity !== 'normal' && !disabled && (
          <span style={{ fontSize: '12px' }} aria-hidden="true">
            {severity === 'critical' ? '⚠' : '△'}
          </span>
        )}
        {label}
        {requiresConfirmation && !disabled && (
          <span
            style={{
              fontSize: '10px',
              color: 'var(--text-muted)',
              fontWeight: 400,
              marginLeft: '2px',
            }}
          >
            (confirm)
          </span>
        )}
      </button>

      {requiresConfirmation && (
        <ControlConfirmationDialog
          open={dialogOpen}
          onConfirm={handleConfirm}
          onCancel={() => setDialogOpen(false)}
          title={confirmationTitle ?? label}
          description={
            confirmationDesc ??
            `You are about to perform the action: "${label}". This is an admin approval-gated execution action. Operator approval remains enforced.`
          }
          severity={dialogSeverity}
          confirmLabel={label}
        />
      )}
    </>
  );
};

export default AdminActionButton;
