import React, { useState, useRef, useEffect } from 'react';

interface ControlConfirmationDialogProps {
  open: boolean;
  onConfirm: (reason: string) => Promise<void>;
  onCancel: () => void;
  title: string;
  description: string;
  severity: 'warning' | 'critical';
  confirmLabel?: string;
}

/**
 * Admin-only confirmation dialog for dangerous approval-gated admin actions.
 * LIVE TRADING: BLOCKED. This dialog must never be wired to any live exchange action.
 */
export const ControlConfirmationDialog: React.FC<ControlConfirmationDialogProps> = ({
  open,
  onConfirm,
  onCancel,
  title,
  description,
  severity,
  confirmLabel = 'Confirm',
}) => {
  const [reason, setReason] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (open) {
      setReason('');
      setError(null);
      setLoading(false);
      setTimeout(() => inputRef.current?.focus(), 60);
    }
  }, [open]);

  if (!open) return null;

  const severityColor = severity === 'critical' ? 'var(--error)' : 'var(--warn)';
  const severityBg =
    severity === 'critical'
      ? 'color-mix(in oklch, var(--error) 10%, transparent)'
      : 'color-mix(in oklch, var(--warn) 10%, transparent)';

  async function handleConfirm() {
    if (!reason.trim()) {
      setError('A reason is required to proceed.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await onConfirm(reason.trim());
      setReason('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Action failed.');
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') onCancel();
  }

  return (
    <div
      data-testid="control-confirmation-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ccd-title"
      onKeyDown={handleKeyDown}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 'var(--z-overlay)' as React.CSSProperties['zIndex'],
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px',
        background: 'var(--bg-overlay)',
        backdropFilter: 'blur(4px)',
      }}
      onClick={e => { if (e.target === e.currentTarget) onCancel(); }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '480px',
          background: 'var(--bg-panel)',
          border: `1px solid ${severityColor}`,
          borderTop: `4px solid ${severityColor}`,
          borderRadius: 'var(--radius-md)',
          boxShadow: 'var(--shadow-strong)',
          display: 'flex',
          flexDirection: 'column',
          gap: '16px',
          padding: '24px',
          fontFamily: 'var(--font-sans)',
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '12px' }}>
          <div>
            <div
              style={{
                fontSize: '10px',
                fontWeight: 700,
                letterSpacing: '0.1em',
                color: severityColor,
                textTransform: 'uppercase',
                marginBottom: '4px',
              }}
            >
              {severity === 'critical' ? '⚠ Critical Admin Action' : '⚠ Warning — Admin Action'}
            </div>
            <h2
              id="ccd-title"
              style={{
                margin: 0,
                fontSize: '16px',
                fontWeight: 700,
                color: 'var(--text-primary)',
              }}
            >
              {title}
            </h2>
          </div>
          <button
            onClick={onCancel}
            aria-label="Cancel"
            disabled={loading}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-muted)',
              cursor: 'pointer',
              fontSize: '18px',
              lineHeight: 1,
              padding: '2px',
              flexShrink: 0,
            }}
          >
            ✕
          </button>
        </div>

        {/* Severity banner */}
        <div
          style={{
            padding: '12px 14px',
            background: severityBg,
            border: `1px solid ${severityColor}`,
            borderRadius: 'var(--radius-sm)',
            fontSize: '13px',
            color: 'var(--text-secondary)',
            lineHeight: 1.55,
          }}
        >
          {description}
        </div>

        {/* Live order routing notice */}
        <div
          style={{
            padding: '8px 12px',
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)',
            fontSize: '11px',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          OPERATOR GATED — This action applies to admin-controlled runtime mode only.
        </div>

        {/* Reason input */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <label
            htmlFor="ccd-reason"
            style={{
              fontSize: '12px',
              fontWeight: 600,
              color: 'var(--text-secondary)',
            }}
          >
            Reason for this action <span style={{ color: severityColor }}>*</span>
          </label>
          <textarea
            id="ccd-reason"
            ref={inputRef}
            value={reason}
            onChange={e => setReason(e.target.value)}
            placeholder="Enter reason..."
            rows={3}
            disabled={loading}
            style={{
              width: '100%',
              boxSizing: 'border-box',
              padding: '10px 12px',
              background: 'var(--bg-elevated)',
              border: `1px solid ${error ? 'var(--error)' : 'var(--border)'}`,
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-primary)',
              fontFamily: 'var(--font-sans)',
              fontSize: '13px',
              resize: 'vertical',
              outline: 'none',
              transition: 'border-color var(--ease-fast)',
            }}
            onFocus={e => (e.currentTarget.style.borderColor = severityColor)}
            onBlur={e =>
              (e.currentTarget.style.borderColor = error ? 'var(--error)' : 'var(--border)')
            }
          />
          {error && (
            <span style={{ fontSize: '12px', color: 'var(--error)' }}>{error}</span>
          )}
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
          <button
            onClick={onCancel}
            disabled={loading}
            style={{
              padding: '8px 20px',
              background: 'transparent',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-secondary)',
              fontSize: '13px',
              fontWeight: 600,
              fontFamily: 'var(--font-sans)',
              cursor: 'pointer',
              transition: 'border-color var(--ease-fast)',
            }}
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={loading || !reason.trim()}
            style={{
              padding: '8px 20px',
              background: loading || !reason.trim() ? 'var(--bg-elevated)' : severityColor,
              border: `1px solid ${severityColor}`,
              borderRadius: 'var(--radius-sm)',
              color: loading || !reason.trim() ? 'var(--text-muted)' : 'var(--text-inverse)',
              fontSize: '13px',
              fontWeight: 700,
              fontFamily: 'var(--font-sans)',
              cursor: loading || !reason.trim() ? 'not-allowed' : 'pointer',
              transition: 'background var(--ease-fast), color var(--ease-fast)',
            }}
          >
            {loading ? 'Processing…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ControlConfirmationDialog;
