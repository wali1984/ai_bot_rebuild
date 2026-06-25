import { useState } from 'react';

export interface ControlSpec {
  action_id: string;
  label: string;
  description: string;
  danger?: boolean;
  requires_reason?: boolean;
  dry_run_endpoint?: string;
  execute_endpoint: string;
}

interface DryRunResult {
  safe: boolean;
  summary: string;
  warnings: string[];
  affected: string[];
}

interface Props {
  spec: ControlSpec;
  onClose: () => void;
  onComplete?: (auditId: string) => void;
}

type Phase = 'confirm' | 'dry_run' | 'dry_run_result' | 'reason' | 'executing' | 'done' | 'error';

export function ControlActionDialog({ spec, onClose, onComplete }: Props): JSX.Element {
  const [phase, setPhase] = useState<Phase>(spec.dry_run_endpoint ? 'dry_run' : 'confirm');
  const [reason, setReason] = useState('');
  const [dryResult, setDryResult] = useState<DryRunResult | null>(null);
  const [auditId, setAuditId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function runDryRun() {
    if (!spec.dry_run_endpoint) return;
    setLoading(true);
    try {
      const resp = await fetch(spec.dry_run_endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ action_id: spec.action_id, dry_run: true }),
      });
      const data = await resp.json() as { safe: boolean; summary: string; warnings?: string[]; affected?: string[] };
      if (!resp.ok) throw new Error(data.summary ?? 'Dry run failed');
      setDryResult({
        safe: data.safe,
        summary: data.summary,
        warnings: data.warnings ?? [],
        affected: data.affected ?? [],
      });
      setPhase('dry_run_result');
    } catch (err) {
      setErrorMsg((err as Error).message);
      setPhase('error');
    } finally {
      setLoading(false);
    }
  }

  async function execute() {
    if (spec.requires_reason && !reason.trim()) return;
    setPhase('executing');
    try {
      const resp = await fetch(spec.execute_endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ action_id: spec.action_id, reason: reason.trim() || undefined }),
      });
      const data = await resp.json() as { audit_id?: string; error?: string };
      if (!resp.ok) throw new Error(data.error ?? 'Execution failed');
      setAuditId(data.audit_id ?? null);
      setPhase('done');
      if (data.audit_id) onComplete?.(data.audit_id);
    } catch (err) {
      setErrorMsg((err as Error).message);
      setPhase('error');
    }
  }

  const dangerStyle = spec.danger ? {
    border: '2px solid color-mix(in oklch, var(--error) 50%, transparent)',
  } : {};

  return (
    <div
      data-testid={`control-dialog-${spec.action_id}`}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.6)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 999,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        style={{
          background: 'var(--bg-panel)',
          borderRadius: 12,
          padding: 24,
          minWidth: 420,
          maxWidth: 580,
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
          ...dangerStyle,
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {spec.danger && (
            <span style={{ color: 'var(--error)', fontSize: 18 }}>⚠</span>
          )}
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text-primary)' }}>{spec.label}</div>
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>{spec.description}</div>
          </div>
          <button type="button" onClick={onClose} style={{ border: 'none', background: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 18, padding: 0 }}>✕</button>
        </div>

        {/* Action ID */}
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', padding: '4px 8px', background: 'var(--bg-elevated)', borderRadius: 4 }}>
          action_id: {spec.action_id}
        </div>

        {/* Phase: dry run */}
        {phase === 'dry_run' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <p style={{ margin: 0, fontSize: 13, color: 'var(--text-secondary)' }}>
              A dry-run will check what would happen without making changes.
            </p>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button type="button" onClick={onClose} style={{ padding: '7px 14px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-elevated)', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: 13 }}>Cancel</button>
              <button type="button" onClick={() => void runDryRun()} disabled={loading} style={{ padding: '7px 14px', borderRadius: 6, border: 'none', background: 'var(--admin-accent)', color: '#fff', cursor: loading ? 'wait' : 'pointer', fontSize: 13, fontWeight: 600 }}>
                {loading ? 'Running…' : 'Run Dry Run'}
              </button>
            </div>
          </div>
        )}

        {/* Phase: dry run result */}
        {phase === 'dry_run_result' && dryResult && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ padding: '10px 14px', borderRadius: 8, background: dryResult.safe ? 'color-mix(in oklch, var(--ok) 8%, var(--bg-elevated))' : 'color-mix(in oklch, var(--error) 8%, var(--bg-elevated))', border: `1px solid ${dryResult.safe ? 'color-mix(in oklch, var(--ok) 30%, transparent)' : 'color-mix(in oklch, var(--error) 30%, transparent)'}` }}>
              <div style={{ fontWeight: 700, color: dryResult.safe ? 'var(--ok)' : 'var(--error)', marginBottom: 4 }}>{dryResult.safe ? '✓ Safe to proceed' : '✗ Not safe'}</div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{dryResult.summary}</div>
            </div>
            {dryResult.warnings.map((w, i) => (
              <div key={i} style={{ fontSize: 12, color: 'var(--warn)', padding: '4px 8px', background: 'color-mix(in oklch, var(--warn) 6%, var(--bg-elevated))', borderRadius: 4 }}>⚠ {w}</div>
            ))}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button type="button" onClick={onClose} style={{ padding: '7px 14px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-elevated)', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: 13 }}>Cancel</button>
              <button type="button" onClick={() => setPhase(spec.requires_reason ? 'reason' : 'confirm')} disabled={!dryResult.safe} style={{ padding: '7px 14px', borderRadius: 6, border: 'none', background: dryResult.safe ? 'var(--admin-accent)' : 'var(--bg-elevated)', color: dryResult.safe ? '#fff' : 'var(--text-muted)', cursor: dryResult.safe ? 'pointer' : 'not-allowed', fontSize: 13, fontWeight: 600 }}>
                Proceed
              </button>
            </div>
          </div>
        )}

        {/* Phase: reason */}
        {phase === 'reason' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <label style={{ fontSize: 13, color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: 6 }}>
              Mandatory reason for this action:
              <textarea
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                rows={3}
                placeholder="Describe why this action is being taken…"
                style={{ padding: '8px 10px', background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text-primary)', fontSize: 12, fontFamily: 'var(--font-sans)', resize: 'vertical' }}
              />
            </label>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button type="button" onClick={onClose} style={{ padding: '7px 14px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-elevated)', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: 13 }}>Cancel</button>
              <button type="button" onClick={() => setPhase('confirm')} disabled={!reason.trim()} style={{ padding: '7px 14px', borderRadius: 6, border: 'none', background: reason.trim() ? 'var(--admin-accent)' : 'var(--bg-elevated)', color: reason.trim() ? '#fff' : 'var(--text-muted)', cursor: reason.trim() ? 'pointer' : 'not-allowed', fontSize: 13, fontWeight: 600 }}>
                Continue
              </button>
            </div>
          </div>
        )}

        {/* Phase: confirm */}
        {phase === 'confirm' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {spec.danger && (
              <div style={{ padding: '10px 14px', borderRadius: 8, background: 'color-mix(in oklch, var(--error) 8%, var(--bg-elevated))', border: '1px solid color-mix(in oklch, var(--error) 30%, transparent)', fontSize: 13, color: 'var(--error)', fontWeight: 600 }}>
                ⚠ This is a dangerous operation. It cannot be automatically reversed.
              </div>
            )}
            {reason && (
              <div style={{ fontSize: 12, color: 'var(--text-secondary)', fontStyle: 'italic' }}>Reason: "{reason}"</div>
            )}
            <p style={{ margin: 0, fontSize: 13, color: 'var(--text-secondary)' }}>
              Confirm execution of <strong style={{ color: 'var(--text-primary)' }}>{spec.label}</strong>?
            </p>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button type="button" onClick={onClose} style={{ padding: '7px 14px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-elevated)', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: 13 }}>Cancel</button>
              <button type="button" data-testid={`control-confirm-${spec.action_id}`} onClick={() => void execute()} style={{ padding: '7px 14px', borderRadius: 6, border: 'none', background: spec.danger ? 'var(--error)' : 'var(--admin-accent)', color: '#fff', cursor: 'pointer', fontSize: 13, fontWeight: 700 }}>
                Confirm
              </button>
            </div>
          </div>
        )}

        {/* Phase: executing */}
        {phase === 'executing' && (
          <div style={{ padding: '16px 0', textAlign: 'center', color: 'var(--text-secondary)', fontSize: 13 }}>
            Executing…
          </div>
        )}

        {/* Phase: done */}
        {phase === 'done' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ padding: '10px 14px', borderRadius: 8, background: 'color-mix(in oklch, var(--ok) 8%, var(--bg-elevated))', border: '1px solid color-mix(in oklch, var(--ok) 30%, transparent)', color: 'var(--ok)', fontWeight: 600, fontSize: 13 }}>
              ✓ Action completed
            </div>
            {auditId && (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
                Audit ID: {auditId}
              </div>
            )}
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button type="button" onClick={onClose} style={{ padding: '7px 14px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-elevated)', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: 13 }}>Close</button>
            </div>
          </div>
        )}

        {/* Phase: error */}
        {phase === 'error' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ padding: '10px 14px', borderRadius: 8, background: 'color-mix(in oklch, var(--error) 8%, var(--bg-elevated))', border: '1px solid color-mix(in oklch, var(--error) 30%, transparent)', color: 'var(--error)', fontSize: 13 }}>
              ✗ {errorMsg ?? 'Unknown error'}
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button type="button" onClick={onClose} style={{ padding: '7px 14px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-elevated)', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: 13 }}>Close</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
