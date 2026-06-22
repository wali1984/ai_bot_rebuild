export type DangerousControlLevel = 'L4' | 'L5';

export interface DangerousControl {
  id: string;
  label: string;
  level: DangerousControlLevel;
  rationale: string;
}

export const DANGEROUS_CONTROLS = {
  enable_live_trading: {
    id: 'enable_live_trading',
    label: 'Enable live trading',
    level: 'L5',
    rationale: 'Default-deny per CLAUDE.md Admin Control Rule. LIVE TRADING: BLOCKED.',
  },
  add_live_api_keys: {
    id: 'add_live_api_keys',
    label: 'Add or activate live API keys',
    level: 'L5',
    rationale: 'Live key activation requires L5 approval and audit chain entry.',
  },
  increase_leverage: {
    id: 'increase_leverage',
    label: 'Increase leverage',
    level: 'L4',
    rationale: 'Leverage escalation requires reviewer approval; capped by risk policy bundle.',
  },
  enable_cross_margin: {
    id: 'enable_cross_margin',
    label: 'Enable CROSS margin',
    level: 'L4',
    rationale: 'CROSS margin elevates liquidation risk; ISOLATED is the default.',
  },
  increase_max_position_size: {
    id: 'increase_max_position_size',
    label: 'Increase max position size',
    level: 'L4',
    rationale: 'Notional cap escalation requires risk gateway re-approval.',
  },
  increase_daily_loss_limit: {
    id: 'increase_daily_loss_limit',
    label: 'Increase daily loss limit',
    level: 'L4',
    rationale: 'Daily loss limit is a kill-switch input; escalation is L4.',
  },
  disable_kill_switch: {
    id: 'disable_kill_switch',
    label: 'Disable kill switch',
    level: 'L5',
    rationale: 'Kill switch is the last line of defense; disabling requires L5.',
  },
  disable_mandatory_stop: {
    id: 'disable_mandatory_stop',
    label: 'Disable mandatory stop',
    level: 'L5',
    rationale: 'Mandatory stop loss enforces survival; disabling requires L5.',
  },
  enable_hedge_dca: {
    id: 'enable_hedge_dca',
    label: 'Enable hedge / DCA',
    level: 'L4',
    rationale: 'Hedge/DCA modify risk envelope; reviewer approval required.',
  },
  enable_adjust_leverage: {
    id: 'enable_adjust_leverage',
    label: 'Enable ADJUST_LEVERAGE',
    level: 'L4',
    rationale: 'Auto-leverage adjustment must be reviewer-approved.',
  },
  switch_paper_to_live: {
    id: 'switch_paper_to_live',
    label: 'Switch runtime to live',
    level: 'L5',
    rationale: 'Runtime-to-live transition is L5 and gated by Live Readiness GO.',
  },
} as const satisfies Record<string, DangerousControl>;

export type DangerousControlId = keyof typeof DANGEROUS_CONTROLS;

export const DANGEROUS_CONTROL_IDS: ReadonlyArray<DangerousControlId> =
  Object.keys(DANGEROUS_CONTROLS) as ReadonlyArray<DangerousControlId>;
