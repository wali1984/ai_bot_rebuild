import { useState } from 'react';
import type { ValidatedDataEnvelope } from '../../types/dataContract';
import { FreshnessBadge } from './FreshnessBadge';
import { SourceBadge } from './SourceBadge';
import { DataQualityBadge } from './DataQualityBadge';
import { lagLabel } from '../../types/dataContract';

interface Props {
  envelope: ValidatedDataEnvelope<unknown>;
  label?: string;
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '140px 1fr',
        gap: 8,
        padding: '4px 0',
        borderBottom: '1px solid var(--border)',
        fontSize: 12,
      }}
    >
      <span style={{ color: 'var(--text-muted)', fontWeight: 500 }}>{label}</span>
      <span style={{ color: 'var(--text-primary)', wordBreak: 'break-all' }}>{value}</span>
    </div>
  );
}

export function EvidenceDrawer({ envelope, label = 'Evidence' }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <div style={{ position: 'relative', display: 'inline-block' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          background: 'none',
          border: '1px solid var(--border)',
          borderRadius: 4,
          color: 'var(--text-secondary)',
          cursor: 'pointer',
          fontSize: 11,
          padding: '2px 8px',
        }}
      >
        {label}
      </button>
      {open && (
        <>
          <div
            style={{
              position: 'fixed',
              inset: 0,
              zIndex: 999,
            }}
            onClick={() => setOpen(false)}
          />
          <div
            style={{
              position: 'absolute',
              right: 0,
              top: '100%',
              marginTop: 4,
              zIndex: 1000,
              width: 400,
              maxHeight: '70vh',
              overflowY: 'auto',
              background: 'var(--bg-elevated)',
              border: '1px solid var(--border-strong)',
              borderRadius: 8,
              padding: 16,
              boxShadow: 'var(--shadow-strong)',
            }}
          >
            <div
              style={{
                fontWeight: 600,
                fontSize: 13,
                marginBottom: 12,
                color: 'var(--text-primary)',
              }}
            >
              Data Evidence
            </div>
            <Row label="Source" value={envelope.source} />
            <Row label="Source type" value={<SourceBadge sourceType={envelope.source_type} source={envelope.source_type} />} />
            <Row label="Freshness" value={<FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />} />
            <Row label="Quality" value={<DataQualityBadge status={envelope.data_quality_status} missingFields={envelope.missing_fields} />} />
            {envelope.endpoint && <Row label="Endpoint" value={envelope.endpoint} />}
            {envelope.stream_topic && <Row label="Stream topic" value={envelope.stream_topic} />}
            {envelope.repository && <Row label="Repository" value={envelope.repository} />}
            {envelope.ingestor_id && <Row label="Ingestor" value={envelope.ingestor_id} />}
            <Row label="Lag" value={lagLabel(envelope.lag_ms)} />
            <Row
              label="Timestamp"
              value={
                envelope.timestamp
                  ? new Date(envelope.timestamp).toISOString()
                  : '—'
              }
            />
            <Row label="Mode" value={envelope.mode} />
            {envelope.model_version && <Row label="Model version" value={envelope.model_version} />}
            {envelope.strategy_id && <Row label="Strategy" value={envelope.strategy_id} />}
            {envelope.missing_fields.length > 0 && (
              <Row
                label="Missing fields"
                value={
                  <span style={{ color: 'var(--warn)' }}>
                    {envelope.missing_fields.join(', ')}
                  </span>
                }
              />
            )}
            {envelope.warnings.length > 0 && (
              <Row
                label="Warnings"
                value={
                  <span style={{ color: 'var(--warn)' }}>
                    {envelope.warnings.join('; ')}
                  </span>
                }
              />
            )}
            {envelope.errors.length > 0 && (
              <Row
                label="Errors"
                value={
                  <span style={{ color: 'var(--error)' }}>
                    {envelope.errors.join('; ')}
                  </span>
                }
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}
