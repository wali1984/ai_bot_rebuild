import { useEffect, useState } from 'react';
import { DEFAULT_LIVE_READINESS, type LiveReadinessPayload } from '../../constants/liveReadiness';

const LABELS = {
  blocked: 'LIVE TRADING: BLOCKED',
  pending: 'LIVE TRADING: PENDING APPROVAL',
  active: 'LIVE TRADING: ACTIVE (bounded)',
} as const;

const TONES = {
  blocked: 'live-block-banner--red',
  pending: 'live-block-banner--amber',
  active: 'live-block-banner--green',
} as const;

export function LiveBlockBanner(): JSX.Element {
  const [payload, setPayload] = useState<LiveReadinessPayload>(DEFAULT_LIVE_READINESS);

  useEffect(() => {
    let cancelled = false;
    async function load(): Promise<void> {
      try {
        const res = await fetch('/api/v1/risk/live-readiness', {
          credentials: 'same-origin',
          headers: { Accept: 'application/json' },
        });
        if (!res.ok) return;
        const data = (await res.json()) as Partial<LiveReadinessPayload>;
        if (cancelled) return;
        if (data.state !== 'active' && data.state !== 'pending') {
          setPayload(DEFAULT_LIVE_READINESS);
          return;
        }
        if (data.state === 'active' && !data.envelope) {
          setPayload(DEFAULT_LIVE_READINESS);
          return;
        }
        setPayload({
          state: data.state,
          envelope: data.envelope ?? null,
          reason_codes: data.reason_codes ?? [],
        });
      } catch {
        if (!cancelled) setPayload(DEFAULT_LIVE_READINESS);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const label = LABELS[payload.state];
  const tone = TONES[payload.state];

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="live-block-banner"
      data-live-state={payload.state}
      className={`live-block-banner ${tone}`}
    >
      <strong className="live-block-banner__label">{label}</strong>
      {payload.state === 'active' && payload.envelope ? (
        <span className="live-block-banner__envelope">
          {' '}— account={payload.envelope.account}, exchange={payload.envelope.exchange},
          notional_cap_usd={payload.envelope.notional_cap_usd},
          leverage_cap={payload.envelope.leverage_cap}
        </span>
      ) : null}
      <span className="live-block-banner__hint"> (banner cannot be dismissed)</span>
    </div>
  );
}
