export type LiveReadinessState = 'blocked' | 'pending' | 'active';

export interface LiveReadinessPayload {
  state: LiveReadinessState;
  envelope?: {
    account: string;
    exchange: string;
    notional_cap_usd: number;
    leverage_cap: number;
  } | null;
  reason_codes: string[];
}

export const DEFAULT_LIVE_READINESS: LiveReadinessPayload = {
  state: 'blocked',
  envelope: null,
  reason_codes: ['default_deny'],
};
