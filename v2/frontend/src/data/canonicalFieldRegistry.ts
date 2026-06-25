import type {
  CanonicalFieldDefinition,
  CanonicalFieldType,
  CanonicalFieldUnit,
  CanonicalFormatter,
  CanonicalFreshness,
  CanonicalNullBehavior,
  CanonicalRoleVisibility,
  CanonicalTraderPage,
} from '../types/canonicalTraderData';

type FieldInput = Omit<CanonicalFieldDefinition, 'roleVisibility'> & {
  roleVisibility?: CanonicalRoleVisibility[];
};

const allTraderPages: CanonicalTraderPage[] = [
  'account-settings',
  'dashboard',
  'portfolio',
  'positions',
  'executions',
  'history',
  'markets',
  'market-detail',
  'trade',
  'derivatives',
  'signals',
  'ai-predictions',
  'backtests',
  'replay',
  'research',
  'technical-analysis',
  'alerts',
];

const accountPages: CanonicalTraderPage[] = ['account-settings', 'dashboard', 'portfolio', 'trade'];
const positionPages: CanonicalTraderPage[] = ['dashboard', 'portfolio', 'positions', 'trade', 'history'];
const marketPages: CanonicalTraderPage[] = ['dashboard', 'markets', 'market-detail', 'trade', 'positions', 'derivatives', 'technical-analysis'];
const signalPages: CanonicalTraderPage[] = ['dashboard', 'signals', 'ai-predictions', 'trade', 'market-detail'];

function staticFreshness(): CanonicalFreshness {
  return { kind: 'static' };
}

function realtimeFreshness(thresholdMs: number): CanonicalFreshness {
  return { kind: 'realtime', threshold_ms: thresholdMs };
}

function accountFreshness(thresholdMs: number): CanonicalFreshness {
  return { kind: 'account_refresh', threshold_ms: thresholdMs };
}

function field(input: FieldInput): CanonicalFieldDefinition {
  return {
    roleVisibility: ['trader', 'admin', 'superadmin'],
    ...input,
  };
}

function accountField(
  id: string,
  label: string,
  canonicalType: CanonicalFieldType,
  unit: CanonicalFieldUnit,
  formatter: CanonicalFormatter,
  decimalPrecision: number | null,
  zeroIsValid: boolean,
  description: string,
  pages = accountPages,
  nullBehavior: CanonicalNullBehavior = 'blocked_for_required_display',
): CanonicalFieldDefinition {
  return field({
    id,
    label,
    canonicalType,
    unit,
    decimalPrecision,
    nullBehavior,
    zeroIsValid,
    preferredSource: '/api/v2/trader/snapshot.account',
    fallbackSource: '/api/auth/me for identity only',
    freshness: accountFreshness(30_000),
    displayFormatter: formatter,
    pages,
    description,
  });
}

function positionField(
  id: string,
  label: string,
  canonicalType: CanonicalFieldType,
  unit: CanonicalFieldUnit,
  formatter: CanonicalFormatter,
  decimalPrecision: number | null,
  zeroIsValid: boolean,
  description: string,
  nullBehavior: CanonicalNullBehavior = 'blocked_for_required_display',
): CanonicalFieldDefinition {
  return field({
    id,
    label,
    canonicalType,
    unit,
    decimalPrecision,
    nullBehavior,
    zeroIsValid,
    preferredSource: '/api/v2/trader/snapshot.positions',
    fallbackSource: 'scoped paper account repository',
    freshness: realtimeFreshness(10_000),
    displayFormatter: formatter,
    pages: positionPages,
    description,
  });
}

function marketField(
  id: string,
  label: string,
  canonicalType: CanonicalFieldType,
  unit: CanonicalFieldUnit,
  formatter: CanonicalFormatter,
  decimalPrecision: number | null,
  zeroIsValid: boolean,
  description: string,
  nullBehavior: CanonicalNullBehavior = 'blocked_for_required_display',
): CanonicalFieldDefinition {
  return field({
    id,
    label,
    canonicalType,
    unit,
    decimalPrecision,
    nullBehavior,
    zeroIsValid,
    preferredSource: '/api/v2/trader/snapshot.market_status',
    fallbackSource: '/api/v2/market/overview or symbol detail read-only market feed',
    freshness: realtimeFreshness(5_000),
    displayFormatter: formatter,
    pages: marketPages,
    description,
  });
}

function signalField(
  id: string,
  label: string,
  canonicalType: CanonicalFieldType,
  unit: CanonicalFieldUnit,
  formatter: CanonicalFormatter,
  decimalPrecision: number | null,
  zeroIsValid: boolean,
  description: string,
  nullBehavior: CanonicalNullBehavior = 'blocked_for_required_display',
): CanonicalFieldDefinition {
  return field({
    id,
    label,
    canonicalType,
    unit,
    decimalPrecision,
    nullBehavior,
    zeroIsValid,
    preferredSource: '/api/v2/trader/snapshot.signals',
    fallbackSource: '/api/v2/signals/all-timeframe-truth',
    freshness: realtimeFreshness(30_000),
    displayFormatter: formatter,
    pages: signalPages,
    description,
  });
}

export const CANONICAL_TRADER_FIELD_REGISTRY: Record<string, CanonicalFieldDefinition> = {
  'account.trader_id': accountField('account.trader_id', 'Trader ID', 'string', 'id', 'id', null, false, 'Backend-authenticated trader identifier.', ['account-settings']),
  'account.account_id': accountField('account.account_id', 'Account ID', 'string', 'id', 'id', null, false, 'Backend-authenticated paper or exchange account scope.', ['account-settings', 'portfolio']),
  'account.mode': accountField('account.mode', 'Mode', 'enum', 'status', 'enumStatus', null, false, 'Account mode. Market data liveness must not imply live execution.', allTraderPages),
  'account.connection_status': accountField('account.connection_status', 'Connection', 'enum', 'status', 'enumStatus', null, false, 'Account connection state: CONNECTED, UNAVAILABLE, or UNAUTHORIZED.', accountPages),
  'account.equity': accountField('account.equity', 'Equity', 'decimal', 'usd', 'usd', 2, true, 'Total account equity from the scoped account read model.'),
  'account.available_balance': accountField('account.available_balance', 'Available Balance', 'decimal', 'usd', 'usd', 2, true, 'Available balance for new paper/read-only account exposure.'),
  'account.used_balance': accountField('account.used_balance', 'Used Balance', 'decimal', 'usd', 'usd', 2, true, 'Margin or balance currently committed to open exposure.'),
  'account.realized_pnl': accountField('account.realized_pnl', 'Realized PnL', 'decimal', 'usd', 'usd', 2, true, 'Realized profit and loss from actual fills or scoped paper ledger.'),
  'account.unrealized_pnl': accountField('account.unrealized_pnl', 'Unrealized PnL', 'decimal', 'usd', 'usd', 2, true, 'Open-position mark-to-market profit and loss.'),
  'account.daily_pnl': accountField('account.daily_pnl', 'Daily PnL', 'decimal', 'usd', 'usd', 2, true, 'Current day account profit and loss from the scoped account read model.'),
  'account.total_pnl': accountField('account.total_pnl', 'Total PnL', 'decimal', 'usd', 'usd', 2, true, 'Realized plus unrealized account profit and loss.'),
  'account.exposure': accountField('account.exposure', 'Exposure', 'decimal', 'usd', 'usd', 2, true, 'Current notional exposure.'),
  'account.drawdown': accountField('account.drawdown', 'Drawdown', 'decimal', 'percent', 'percent', 2, true, 'Current drawdown percentage.'),
  'account.open_position_count': accountField('account.open_position_count', 'Open Positions', 'integer', 'count', 'integer', 0, true, 'Open position count for the scoped account.'),
  'account.open_order_count': accountField('account.open_order_count', 'Open Orders', 'integer', 'count', 'integer', 0, true, 'Open order count for the scoped account.'),
  'account.execution_count': accountField('account.execution_count', 'Executions', 'integer', 'count', 'integer', 0, true, 'Execution count for the selected period.'),

  'position.id': positionField('position.id', 'Position ID', 'string', 'id', 'id', null, false, 'Stable position identifier.'),
  'position.symbol': positionField('position.symbol', 'Symbol', 'string', 'symbol', 'symbol', null, false, 'Instrument symbol.'),
  'position.side': positionField('position.side', 'Side', 'enum', 'side', 'side', null, false, 'Position side.'),
  'position.quantity': positionField('position.quantity', 'Quantity', 'decimal', 'base_asset', 'quantity', 8, false, 'Open quantity.'),
  'position.entry_price': positionField('position.entry_price', 'Entry', 'decimal', 'usd', 'price', 8, false, 'Average entry price from order/fill records.'),
  'position.entry_price_source': positionField('position.entry_price_source', 'Entry Source', 'string', 'text', 'text', null, false, 'Source of the entry price.'),
  'position.mark_price': positionField('position.mark_price', 'Mark', 'decimal', 'usd', 'price', 8, false, 'Realtime mark price.'),
  'position.mark_price_source': positionField('position.mark_price_source', 'Mark Source', 'string', 'text', 'text', null, false, 'Source of the mark price.'),
  'position.mark_age_ms': positionField('position.mark_age_ms', 'Mark Age', 'integer', 'milliseconds', 'ageMs', 0, true, 'Age of the mark price update in milliseconds.'),
  'position.exit_price': positionField('position.exit_price', 'Exit', 'decimal', 'usd', 'price', 8, false, 'Actual exit price when the position is closed.', 'allowed_when_not_applicable'),
  'position.exit_price_source': positionField('position.exit_price_source', 'Exit Source', 'string', 'text', 'text', null, false, 'Source of the exit price.', 'allowed_when_not_applicable'),
  'position.notional': positionField('position.notional', 'Notional', 'decimal', 'usd', 'usd', 2, false, 'Position notional value.'),
  'position.unrealized_pnl': positionField('position.unrealized_pnl', 'Unrealized PnL', 'decimal', 'usd', 'usd', 2, true, 'Position unrealized profit and loss.'),
  'position.realized_pnl': positionField('position.realized_pnl', 'Realized PnL', 'decimal', 'usd', 'usd', 2, true, 'Position realized profit and loss.'),
  'position.pnl_percent': positionField('position.pnl_percent', 'PnL %', 'decimal', 'percent', 'percent', 2, true, 'Position profit and loss percentage.'),
  'position.stop': positionField('position.stop', 'Stop', 'decimal', 'usd', 'price', 8, false, 'Active stop price.', 'allowed_when_not_applicable'),
  'position.targets': positionField('position.targets', 'Targets', 'array', 'usd', 'jsonList', 8, false, 'Active target prices.', 'allowed_when_not_applicable'),
  'position.liquidation_price': positionField('position.liquidation_price', 'Liquidation', 'decimal', 'usd', 'price', 8, false, 'Liquidation price when provided by source.', 'allowed_when_not_applicable'),
  'position.strategy_id': positionField('position.strategy_id', 'Strategy', 'string', 'id', 'id', null, false, 'Originating strategy identifier.', 'allowed_when_not_applicable'),
  'position.signal_id': positionField('position.signal_id', 'Signal', 'string', 'id', 'id', null, false, 'Originating signal identifier.', 'allowed_when_not_applicable'),
  'position.prediction_id': positionField('position.prediction_id', 'Prediction', 'string', 'id', 'id', null, false, 'Originating prediction identifier.', 'allowed_when_not_applicable'),
  'position.risk_status': positionField('position.risk_status', 'Risk', 'enum', 'status', 'enumStatus', null, false, 'Risk state attached to the position.'),
  'position.decision_reasoning': positionField('position.decision_reasoning', 'Reasoning', 'string', 'text', 'text', null, false, 'Decision explanation attached to the position.', 'allowed_when_not_applicable'),
  'position.updated_at': positionField('position.updated_at', 'Updated', 'timestamp', 'timestamp', 'timestamp', null, false, 'Last position update timestamp.'),

  'market.symbol': marketField('market.symbol', 'Symbol', 'string', 'symbol', 'symbol', null, false, 'Instrument symbol.'),
  'market.last_price': marketField('market.last_price', 'Last', 'decimal', 'usd', 'price', 8, false, 'Last traded price.'),
  'market.mark_price': marketField('market.mark_price', 'Mark', 'decimal', 'usd', 'price', 8, false, 'Exchange mark price.'),
  'market.index_price': marketField('market.index_price', 'Index', 'decimal', 'usd', 'price', 8, false, 'Exchange index price.'),
  'market.change_1h': marketField('market.change_1h', '1h Change', 'decimal', 'percent', 'percent', 2, true, 'One-hour percentage change.', 'allowed_when_source_missing'),
  'market.change_4h': marketField('market.change_4h', '4h Change', 'decimal', 'percent', 'percent', 2, true, 'Four-hour percentage change.', 'allowed_when_source_missing'),
  'market.change_24h': marketField('market.change_24h', '24h Change', 'decimal', 'percent', 'percent', 2, true, 'Twenty-four-hour percentage change.'),
  'market.high_24h': marketField('market.high_24h', '24h High', 'decimal', 'usd', 'price', 8, false, 'Twenty-four-hour high price.'),
  'market.low_24h': marketField('market.low_24h', '24h Low', 'decimal', 'usd', 'price', 8, false, 'Twenty-four-hour low price.'),
  'market.volume_24h': marketField('market.volume_24h', '24h Volume', 'decimal', 'base_asset', 'quantity', 4, true, 'Twenty-four-hour traded base volume.'),
  'market.turnover_24h': marketField('market.turnover_24h', '24h Turnover', 'decimal', 'usd', 'usd', 2, true, 'Twenty-four-hour quote turnover.'),
  'market.spread': marketField('market.spread', 'Spread', 'decimal', 'usd', 'price', 8, true, 'Best ask minus best bid.'),
  'market.funding_rate': marketField('market.funding_rate', 'Funding', 'decimal', 'percent', 'percent', 4, true, 'Current funding rate.', 'allowed_when_source_missing'),
  'market.predicted_funding': marketField('market.predicted_funding', 'Predicted Funding', 'decimal', 'percent', 'percent', 4, true, 'Predicted next funding rate.', 'allowed_when_source_missing'),
  'market.open_interest': marketField('market.open_interest', 'Open Interest', 'decimal', 'contract', 'quantity', 4, true, 'Current open interest.', 'allowed_when_source_missing'),
  'market.oi_change_1h': marketField('market.oi_change_1h', 'OI 1h', 'decimal', 'percent', 'percent', 2, true, 'One-hour open-interest change.', 'allowed_when_source_missing'),
  'market.oi_change_4h': marketField('market.oi_change_4h', 'OI 4h', 'decimal', 'percent', 'percent', 2, true, 'Four-hour open-interest change.', 'allowed_when_source_missing'),
  'market.oi_change_24h': marketField('market.oi_change_24h', 'OI 24h', 'decimal', 'percent', 'percent', 2, true, 'Twenty-four-hour open-interest change.', 'allowed_when_source_missing'),
  'market.liquidations_1h': marketField('market.liquidations_1h', '1h Liquidations', 'decimal', 'usd', 'usd', 2, true, 'One-hour liquidation notional.', 'allowed_when_source_missing'),
  'market.liquidations_24h': marketField('market.liquidations_24h', '24h Liquidations', 'decimal', 'usd', 'usd', 2, true, 'Twenty-four-hour liquidation notional.', 'allowed_when_source_missing'),
  'market.long_short_ratio': marketField('market.long_short_ratio', 'Long/Short', 'decimal', 'ratio', 'ratio', 4, false, 'Long/short account or position ratio.', 'allowed_when_source_missing'),

  'signal.id': signalField('signal.id', 'Signal ID', 'string', 'id', 'id', null, false, 'Stable signal identifier.'),
  'signal.symbol': signalField('signal.symbol', 'Symbol', 'string', 'symbol', 'symbol', null, false, 'Signal instrument symbol.'),
  'signal.direction': signalField('signal.direction', 'Direction', 'enum', 'side', 'side', null, false, 'Signal direction.'),
  'signal.timeframe': signalField('signal.timeframe', 'Timeframe', 'string', 'text', 'text', null, false, 'Signal timeframe.'),
  'signal.entry': signalField('signal.entry', 'Entry', 'decimal', 'usd', 'price', 8, false, 'Signal entry price.'),
  'signal.targets': signalField('signal.targets', 'Targets', 'array', 'usd', 'jsonList', 8, false, 'Signal target prices.', 'allowed_when_not_applicable'),
  'signal.stop': signalField('signal.stop', 'Stop', 'decimal', 'usd', 'price', 8, false, 'Signal stop price.', 'allowed_when_not_applicable'),
  'signal.invalidation': signalField('signal.invalidation', 'Invalidation', 'decimal', 'usd', 'price', 8, false, 'Signal invalidation price.', 'allowed_when_not_applicable'),
  'signal.confidence': signalField('signal.confidence', 'Confidence', 'decimal', 'percent', 'percent', 2, true, 'Model confidence percentage.'),
  'signal.expected_move': signalField('signal.expected_move', 'Expected Move', 'decimal', 'percent', 'percent', 2, true, 'Expected move percentage.'),
  'signal.risk_reward': signalField('signal.risk_reward', 'Risk/Reward', 'decimal', 'ratio', 'ratio', 2, false, 'Risk/reward ratio.'),
  'signal.status': signalField('signal.status', 'Status', 'enum', 'status', 'enumStatus', null, false, 'Signal status.'),
  'signal.strategy': signalField('signal.strategy', 'Strategy', 'string', 'text', 'text', null, false, 'Originating strategy label or ID.'),
  'signal.model_version': signalField('signal.model_version', 'Model', 'string', 'text', 'text', null, false, 'Model version that produced the signal.'),
  'signal.risk_decision': signalField('signal.risk_decision', 'Risk Decision', 'enum', 'status', 'enumStatus', null, false, 'Risk decision attached to the signal.'),
  'signal.created_at': signalField('signal.created_at', 'Created', 'timestamp', 'timestamp', 'timestamp', null, false, 'Signal creation timestamp.'),
  'signal.expires_at': signalField('signal.expires_at', 'Expires', 'timestamp', 'timestamp', 'timestamp', null, false, 'Signal expiration timestamp.', 'allowed_when_not_applicable'),
  'signal.evidence': signalField('signal.evidence', 'Evidence', 'array', 'text', 'jsonList', null, false, 'Evidence lineage used for the signal.'),
};

export const CANONICAL_TRADER_FIELD_IDS = Object.keys(CANONICAL_TRADER_FIELD_REGISTRY);

export type CanonicalTraderFieldId = keyof typeof CANONICAL_TRADER_FIELD_REGISTRY;

export function getCanonicalTraderField(id: string): CanonicalFieldDefinition | null {
  return CANONICAL_TRADER_FIELD_REGISTRY[id] ?? null;
}

export function canonicalFieldsForPage(page: CanonicalTraderPage): CanonicalFieldDefinition[] {
  return Object.values(CANONICAL_TRADER_FIELD_REGISTRY).filter((definition) => definition.pages.includes(page));
}

export function isCanonicalTraderFieldId(id: string): id is CanonicalTraderFieldId {
  return id in CANONICAL_TRADER_FIELD_REGISTRY;
}
