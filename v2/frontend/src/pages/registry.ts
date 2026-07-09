import type { PageModule } from '../types/page';
import { resolvePageModule } from './productNavigation';

// ── Canonical admin pages (new consolidated IA) ──────────────────────────────
import AdminOverviewPage from './admin-overview';
import adminOverviewMeta from './admin-overview/meta';
import adminOverviewRbac from './admin-overview/rbac';
import adminOverviewRoute from './admin-overview/route';

import AdminDataPage from './admin-data';
import adminDataMeta from './admin-data/meta';
import adminDataRbac from './admin-data/rbac';
import adminDataRoute from './admin-data/route';

import AdminIntelligencePage from './admin-intelligence';
import adminIntelligenceMeta from './admin-intelligence/meta';
import adminIntelligenceRbac from './admin-intelligence/rbac';
import adminIntelligenceRoute from './admin-intelligence/route';

import AdminOrchestrationPage from './admin-orchestration';
import adminOrchestrationMeta from './admin-orchestration/meta';
import adminOrchestrationRbac from './admin-orchestration/rbac';
import adminOrchestrationRoute from './admin-orchestration/route';

import AdminRiskPage from './admin-risk';
import adminRiskMeta from './admin-risk/meta';
import adminRiskRbac from './admin-risk/rbac';
import adminRiskRoute from './admin-risk/route';

import AdminExecutionPage from './admin-execution';
import adminExecutionMeta from './admin-execution/meta';
import adminExecutionRbac from './admin-execution/rbac';
import adminExecutionRoute from './admin-execution/route';

import AdminExchangesPage from './admin-exchanges';
import adminExchangesMeta from './admin-exchanges/meta';
import adminExchangesRbac from './admin-exchanges/rbac';
import adminExchangesRoute from './admin-exchanges/route';

import AdminConfigPage from './admin-config';
import adminConfigMeta from './admin-config/meta';
import adminConfigRbac from './admin-config/rbac';
import adminConfigRoute from './admin-config/route';

import AdminUsersPage from './admin-users';
import adminUsersMeta from './admin-users/meta';
import adminUsersRbac from './admin-users/rbac';
import adminUsersRoute from './admin-users/route';

import AdminReportsPage from './admin-reports';
import adminReportsMeta from './admin-reports/meta';
import adminReportsRbac from './admin-reports/rbac';
import adminReportsRoute from './admin-reports/route';

import AdminLogsPage from './admin-logs';
import adminLogsMeta from './admin-logs/meta';
import adminLogsRbac from './admin-logs/rbac';
import adminLogsRoute from './admin-logs/route';

import AdminAuditPage from './admin-audit';
import adminAuditMeta from './admin-audit/meta';
import adminAuditRbac from './admin-audit/rbac';
import adminAuditRoute from './admin-audit/route';

import AdminToolsPage from './admin-tools';
import adminToolsMeta from './admin-tools/meta';
import adminToolsRbac from './admin-tools/rbac';
import adminToolsRoute from './admin-tools/route';

// ── Legacy pages (kept as redirect stubs / still registered at old paths) ────
import DashboardPage from './dashboard';
import dashboardMeta from './dashboard/meta';
import dashboardRbac from './dashboard/rbac';
import dashboardRoute from './dashboard/route';

import MissionControlPage from './mission-control';
import missionControlMeta from './mission-control/meta';
import missionControlRbac from './mission-control/rbac';
import missionControlRoute from './mission-control/route';

import MonitorCenterPage from './monitor-center';
import monitorCenterMeta from './monitor-center/meta';
import monitorCenterRbac from './monitor-center/rbac';
import monitorCenterRoute from './monitor-center/route';

import CoverageSystemAtlasPage from './coverage-system-atlas';
import coverageSystemAtlasMeta from './coverage-system-atlas/meta';
import coverageSystemAtlasRbac from './coverage-system-atlas/rbac';
import coverageSystemAtlasRoute from './coverage-system-atlas/route';

import ScriptRegistryPage from './script-registry';
import scriptRegistryMeta from './script-registry/meta';
import scriptRegistryRbac from './script-registry/rbac';
import scriptRegistryRoute from './script-registry/route';

import TrainerPredictionMonitorPage from './trainer-prediction-monitor';
import trainerPredictionMonitorMeta from './trainer-prediction-monitor/meta';
import trainerPredictionMonitorRbac from './trainer-prediction-monitor/rbac';
import trainerPredictionMonitorRoute from './trainer-prediction-monitor/route';

import SignalExplainabilityPage from './signal-explainability';
import signalExplainabilityMeta from './signal-explainability/meta';
import signalExplainabilityRbac from './signal-explainability/rbac';
import signalExplainabilityRoute from './signal-explainability/route';

import SymbolsPage from './symbols';
import symbolsMeta from './symbols/meta';
import symbolsRbac from './symbols/rbac';
import symbolsRoute from './symbols/route';

import MarketIntelligencePage from './market-intelligence';
import marketIntelligenceMeta from './market-intelligence/meta';
import marketIntelligenceRbac from './market-intelligence/rbac';
import marketIntelligenceRoute from './market-intelligence/route';

import SignalsPage from './signals';
import signalsMeta from './signals/meta';
import signalsRbac from './signals/rbac';
import signalsRoute from './signals/route';

import ExecutionsPage from './executions';
import executionsMeta from './executions/meta';
import executionsRbac from './executions/rbac';
import executionsRoute from './executions/route';

import PositionsPage from './positions';
import positionsMeta from './positions/meta';
import positionsRbac from './positions/rbac';
import positionsRoute from './positions/route';

import RiskPage from './risk';
import riskMeta from './risk/meta';
import riskRbac from './risk/rbac';
import riskRoute from './risk/route';

import RiskControlPage from './risk-control';
import riskControlMeta from './risk-control/meta';
import riskControlRbac from './risk-control/rbac';
import riskControlRoute from './risk-control/route';

import ExchangeManagerPage from './exchange-manager';
import exchangeManagerMeta from './exchange-manager/meta';
import exchangeManagerRbac from './exchange-manager/rbac';
import exchangeManagerRoute from './exchange-manager/route';

import ExternalManualPositionQuarantinePage from './external-manual-position-quarantine';
import externalManualPositionQuarantineMeta from './external-manual-position-quarantine/meta';
import externalManualPositionQuarantineRbac from './external-manual-position-quarantine/rbac';
import externalManualPositionQuarantineRoute from './external-manual-position-quarantine/route';

import ConfigAdminPage from './config-admin';
import configAdminMeta from './config-admin/meta';
import configAdminRbac from './config-admin/rbac';
import configAdminRoute from './config-admin/route';

import StrategyAdminPage from './strategy-admin';
import strategyAdminMeta from './strategy-admin/meta';
import strategyAdminRbac from './strategy-admin/rbac';
import strategyAdminRoute from './strategy-admin/route';

import TrainerAdminPage from './trainer-admin';
import trainerAdminMeta from './trainer-admin/meta';
import trainerAdminRbac from './trainer-admin/rbac';
import trainerAdminRoute from './trainer-admin/route';

import OrchestratorAdminPage from './orchestrator-admin';
import orchestratorAdminMeta from './orchestrator-admin/meta';
import orchestratorAdminRbac from './orchestrator-admin/rbac';
import orchestratorAdminRoute from './orchestrator-admin/route';

import ExecutionAdminPage from './execution-admin';
import executionAdminMeta from './execution-admin/meta';
import executionAdminRbac from './execution-admin/rbac';
import executionAdminRoute from './execution-admin/route';

import PaperTradingPage from './paper-trading';
import paperTradingMeta from './paper-trading/meta';
import paperTradingRbac from './paper-trading/rbac';
import paperTradingRoute from './paper-trading/route';

import ReplayPage from './replay';
import replayMeta from './replay/meta';
import replayRbac from './replay/rbac';
import replayRoute from './replay/route';

import AuditLedgerPage from './audit-ledger';
import auditLedgerMeta from './audit-ledger/meta';
import auditLedgerRbac from './audit-ledger/rbac';
import auditLedgerRoute from './audit-ledger/route';

import SystemHealthPage from './system-health';
import systemHealthMeta from './system-health/meta';
import systemHealthRbac from './system-health/rbac';
import systemHealthRoute from './system-health/route';

import LiveCanaryPage from './live-canary';
import liveCanaryMeta from './live-canary/meta';
import liveCanaryRbac from './live-canary/rbac';
import liveCanaryRoute from './live-canary/route';

import LiveReadinessPage from './live-readiness';
import liveReadinessMeta from './live-readiness/meta';
import liveReadinessRbac from './live-readiness/rbac';
import liveReadinessRoute from './live-readiness/route';

import ClaudeAdminAiPage from './claude-admin-ai';
import claudeAdminAiMeta from './claude-admin-ai/meta';
import claudeAdminAiRbac from './claude-admin-ai/rbac';
import claudeAdminAiRoute from './claude-admin-ai/route';

import OllamaLocalAssistantPage from './ollama-local-assistant';
import ollamaLocalAssistantMeta from './ollama-local-assistant/meta';
import ollamaLocalAssistantRbac from './ollama-local-assistant/rbac';
import ollamaLocalAssistantRoute from './ollama-local-assistant/route';

import CodexReviewCenterPage from './codex-review-center';
import codexReviewCenterMeta from './codex-review-center/meta';
import codexReviewCenterRbac from './codex-review-center/rbac';
import codexReviewCenterRoute from './codex-review-center/route';

import BuildValidationStatusPage from './build-validation-status';
import buildValidationStatusMeta from './build-validation-status/meta';
import buildValidationStatusRbac from './build-validation-status/rbac';
import buildValidationStatusRoute from './build-validation-status/route';

import OperatorProofDashboardPage from './operator-proof-dashboard';
import operatorProofDashboardMeta from './operator-proof-dashboard/meta';
import operatorProofDashboardRbac from './operator-proof-dashboard/rbac';
import operatorProofDashboardRoute from './operator-proof-dashboard/route';

import MobileIphoneReadinessPage from './mobile-iphone-readiness';
import mobileIphoneReadinessMeta from './mobile-iphone-readiness/meta';
import mobileIphoneReadinessRbac from './mobile-iphone-readiness/rbac';
import mobileIphoneReadinessRoute from './mobile-iphone-readiness/route';

import PublicLandingPage from './public-landing';
import publicLandingMeta from './public-landing/meta';
import publicLandingRbac from './public-landing/rbac';
import publicLandingRoute from './public-landing/route';

import PublicStatusPage from './public-status';
import publicStatusMeta from './public-status/meta';
import publicStatusRbac from './public-status/rbac';
import publicStatusRoute from './public-status/route';

import LoginPage from './login';
import loginMeta from './login/meta';
import loginRbac from './login/rbac';
import loginRoute from './login/route';

import PermanentMigrationPage from './permanent-migration';
import permanentMigrationMeta from './permanent-migration/meta';
import permanentMigrationRbac from './permanent-migration/rbac';
import permanentMigrationRoute from './permanent-migration/route';

import AccountSettingsPage from './account-settings';
import accountSettingsMeta from './account-settings/meta';
import accountSettingsRbac from './account-settings/rbac';
import accountSettingsRoute from './account-settings/route';

import AdminWarRoomPage from './admin-war-room';
import adminWarRoomMeta from './admin-war-room/meta';
import adminWarRoomRbac from './admin-war-room/rbac';
import adminWarRoomRoute from './admin-war-room/route';

import AiBrainPage from './ai-brain';
import aiBrainMeta from './ai-brain/meta';
import aiBrainRbac from './ai-brain/rbac';
import aiBrainRoute from './ai-brain/route';

import AiPredictionsPage from './ai-predictions';
import aiPredictionsMeta from './ai-predictions/meta';
import aiPredictionsRbac from './ai-predictions/rbac';
import aiPredictionsRoute from './ai-predictions/route';

import BinancePage from './binance';
import binanceMeta from './binance/meta';
import binanceRbac from './binance/rbac';
import binanceRoute from './binance/route';

import AlertsPage from './alerts';
import alertsMeta from './alerts/meta';
import alertsRbac from './alerts/rbac';
import alertsRoute from './alerts/route';

import ExecutiveStatusPage from './executive-status';
import executiveStatusMeta from './executive-status/meta';
import executiveStatusRbac from './executive-status/rbac';
import executiveStatusRoute from './executive-status/route';

import HistoryPage from './history';
import historyMeta from './history/meta';
import historyRbac from './history/rbac';
import historyRoute from './history/route';

import IngestorsPage from './ingestors';
import ingestorsMeta from './ingestors/meta';
import ingestorsRbac from './ingestors/rbac';
import ingestorsRoute from './ingestors/route';

import OrderbookRuntimeTruthPage from './orderbook-runtime-truth';
import orderbookRuntimeTruthMeta from './orderbook-runtime-truth/meta';
import orderbookRuntimeTruthRbac from './orderbook-runtime-truth/rbac';
import orderbookRuntimeTruthRoute from './orderbook-runtime-truth/route';

import MicrostructureTrustPage from './microstructure-trust';
import microstructureTrustMeta from './microstructure-trust/meta';
import microstructureTrustRbac from './microstructure-trust/rbac';
import microstructureTrustRoute from './microstructure-trust/route';

import LiquidationBridgePage from './liquidation-bridge';
import liquidationBridgeMeta from './liquidation-bridge/meta';
import liquidationBridgeRbac from './liquidation-bridge/rbac';
import liquidationBridgeRoute from './liquidation-bridge/route';

import LogsErrorsPage from './logs-errors';
import logsErrorsMeta from './logs-errors/meta';
import logsErrorsRbac from './logs-errors/rbac';
import logsErrorsRoute from './logs-errors/route';

import MarketPage from './market';
import marketMeta from './market/meta';
import marketRbac from './market/rbac';
import marketRoute from './market/route';

// market-root omitted: /market is handled by MERGED_LEGACY_PATHS → /markets

import MarketsPage from './markets';
import marketsMeta from './markets/meta';
import marketsRbac from './markets/rbac';
import marketsRoute from './markets/route';

import MarketsIngestorsPage from './markets-ingestors';
import marketsIngestorsMeta from './markets-ingestors/meta';
import marketsIngestorsRbac from './markets-ingestors/rbac';
import marketsIngestorsRoute from './markets-ingestors/route';

import ProChartPage from './pro-chart';
import proChartMeta from './pro-chart/meta';
import proChartRbac from './pro-chart/rbac';
import proChartRoute from './pro-chart/route';

import PublicLandingV2Page from './public-landing-v2';
import publicLandingV2Meta from './public-landing-v2/meta';
import publicLandingV2Rbac from './public-landing-v2/rbac';
import publicLandingV2Route from './public-landing-v2/route';

import ReportCenterPage from './report-center';
import reportCenterMeta from './report-center/meta';
import reportCenterRbac from './report-center/rbac';
import reportCenterRoute from './report-center/route';

import StrategyBacktestingPage from './strategy-backtesting';
import strategyBacktestingMeta from './strategy-backtesting/meta';
import strategyBacktestingRbac from './strategy-backtesting/rbac';
import strategyBacktestingRoute from './strategy-backtesting/route';

import BacktestsReplayPage from './backtests-replay';
import backtestsReplayMeta from './backtests-replay/meta';
import backtestsReplayRbac from './backtests-replay/rbac';
import backtestsReplayRoute from './backtests-replay/route';

import TechnicalAnalysisPage from './technical-analysis';
import technicalAnalysisMeta from './technical-analysis/meta';
import technicalAnalysisRbac from './technical-analysis/rbac';
import technicalAnalysisRoute from './technical-analysis/route';

import TraderPage from './trader';
import traderMeta from './trader/meta';
import traderRbac from './trader/rbac';
import traderRoute from './trader/route';

// trader-legacy omitted: /trader is handled by MERGED_LEGACY_PATHS → /trade

import UserStatusPage from './user-status';
import userStatusMeta from './user-status/meta';
import userStatusRbac from './user-status/rbac';
import userStatusRoute from './user-status/route';

import MarketBrainPage from './market-brain';
import marketBrainMeta from './market-brain/meta';
import marketBrainRbac from './market-brain/rbac';
import marketBrainRoute from './market-brain/route';

// config-admin-alias removed: /admin/config is owned by admin-config canonical page

const RAW_PAGES: ReadonlyArray<PageModule> = [
  // ── Canonical admin pages (10 primary + 3 secondary) ─────────────────────
  { meta: adminOverviewMeta, rbac: adminOverviewRbac, route: adminOverviewRoute, Component: AdminOverviewPage },
  { meta: adminDataMeta, rbac: adminDataRbac, route: adminDataRoute, Component: AdminDataPage },
  { meta: adminIntelligenceMeta, rbac: adminIntelligenceRbac, route: adminIntelligenceRoute, Component: AdminIntelligencePage },
  { meta: adminOrchestrationMeta, rbac: adminOrchestrationRbac, route: adminOrchestrationRoute, Component: AdminOrchestrationPage },
  { meta: adminRiskMeta, rbac: adminRiskRbac, route: adminRiskRoute, Component: AdminRiskPage },
  { meta: adminExecutionMeta, rbac: adminExecutionRbac, route: adminExecutionRoute, Component: AdminExecutionPage },
  { meta: adminExchangesMeta, rbac: adminExchangesRbac, route: adminExchangesRoute, Component: AdminExchangesPage },
  { meta: adminConfigMeta, rbac: adminConfigRbac, route: adminConfigRoute, Component: AdminConfigPage },
  { meta: adminUsersMeta, rbac: adminUsersRbac, route: adminUsersRoute, Component: AdminUsersPage },
  { meta: adminReportsMeta, rbac: adminReportsRbac, route: adminReportsRoute, Component: AdminReportsPage },
  { meta: adminLogsMeta, rbac: adminLogsRbac, route: adminLogsRoute, Component: AdminLogsPage },
  { meta: adminAuditMeta, rbac: adminAuditRbac, route: adminAuditRoute, Component: AdminAuditPage },
  { meta: adminToolsMeta, rbac: adminToolsRbac, route: adminToolsRoute, Component: AdminToolsPage },

  // ── Trader app pages ────────────────────────────────────────────────────────
  { meta: dashboardMeta, rbac: dashboardRbac, route: dashboardRoute, Component: DashboardPage },
  { meta: permanentMigrationMeta, rbac: permanentMigrationRbac, route: permanentMigrationRoute, Component: PermanentMigrationPage },
  { meta: missionControlMeta, rbac: missionControlRbac, route: missionControlRoute, Component: MissionControlPage },
  { meta: monitorCenterMeta, rbac: monitorCenterRbac, route: monitorCenterRoute, Component: MonitorCenterPage },
  { meta: coverageSystemAtlasMeta, rbac: coverageSystemAtlasRbac, route: coverageSystemAtlasRoute, Component: CoverageSystemAtlasPage },
  { meta: scriptRegistryMeta, rbac: scriptRegistryRbac, route: scriptRegistryRoute, Component: ScriptRegistryPage },
  { meta: trainerPredictionMonitorMeta, rbac: trainerPredictionMonitorRbac, route: trainerPredictionMonitorRoute, Component: TrainerPredictionMonitorPage },
  { meta: signalExplainabilityMeta, rbac: signalExplainabilityRbac, route: signalExplainabilityRoute, Component: SignalExplainabilityPage },
  { meta: symbolsMeta, rbac: symbolsRbac, route: symbolsRoute, Component: SymbolsPage },
  { meta: marketIntelligenceMeta, rbac: marketIntelligenceRbac, route: marketIntelligenceRoute, Component: MarketIntelligencePage },
  { meta: signalsMeta, rbac: signalsRbac, route: signalsRoute, Component: SignalsPage },
  { meta: executionsMeta, rbac: executionsRbac, route: executionsRoute, Component: ExecutionsPage },
  { meta: positionsMeta, rbac: positionsRbac, route: positionsRoute, Component: PositionsPage },
  { meta: riskMeta, rbac: riskRbac, route: riskRoute, Component: RiskPage },
  { meta: riskControlMeta, rbac: riskControlRbac, route: riskControlRoute, Component: RiskControlPage },
  { meta: exchangeManagerMeta, rbac: exchangeManagerRbac, route: exchangeManagerRoute, Component: ExchangeManagerPage },
  { meta: externalManualPositionQuarantineMeta, rbac: externalManualPositionQuarantineRbac, route: externalManualPositionQuarantineRoute, Component: ExternalManualPositionQuarantinePage },
  { meta: configAdminMeta, rbac: configAdminRbac, route: configAdminRoute, Component: ConfigAdminPage },
  { meta: strategyAdminMeta, rbac: strategyAdminRbac, route: strategyAdminRoute, Component: StrategyAdminPage },
  { meta: trainerAdminMeta, rbac: trainerAdminRbac, route: trainerAdminRoute, Component: TrainerAdminPage },
  { meta: orchestratorAdminMeta, rbac: orchestratorAdminRbac, route: orchestratorAdminRoute, Component: OrchestratorAdminPage },
  { meta: executionAdminMeta, rbac: executionAdminRbac, route: executionAdminRoute, Component: ExecutionAdminPage },
  { meta: paperTradingMeta, rbac: paperTradingRbac, route: paperTradingRoute, Component: PaperTradingPage },
  { meta: replayMeta, rbac: replayRbac, route: replayRoute, Component: ReplayPage },
  { meta: auditLedgerMeta, rbac: auditLedgerRbac, route: auditLedgerRoute, Component: AuditLedgerPage },
  { meta: systemHealthMeta, rbac: systemHealthRbac, route: systemHealthRoute, Component: SystemHealthPage },
  { meta: liveCanaryMeta, rbac: liveCanaryRbac, route: liveCanaryRoute, Component: LiveCanaryPage },
  { meta: liveReadinessMeta, rbac: liveReadinessRbac, route: liveReadinessRoute, Component: LiveReadinessPage },
  { meta: claudeAdminAiMeta, rbac: claudeAdminAiRbac, route: claudeAdminAiRoute, Component: ClaudeAdminAiPage },
  { meta: ollamaLocalAssistantMeta, rbac: ollamaLocalAssistantRbac, route: ollamaLocalAssistantRoute, Component: OllamaLocalAssistantPage },
  { meta: codexReviewCenterMeta, rbac: codexReviewCenterRbac, route: codexReviewCenterRoute, Component: CodexReviewCenterPage },
  { meta: buildValidationStatusMeta, rbac: buildValidationStatusRbac, route: buildValidationStatusRoute, Component: BuildValidationStatusPage },
  { meta: operatorProofDashboardMeta, rbac: operatorProofDashboardRbac, route: operatorProofDashboardRoute, Component: OperatorProofDashboardPage },
  { meta: mobileIphoneReadinessMeta, rbac: mobileIphoneReadinessRbac, route: mobileIphoneReadinessRoute, Component: MobileIphoneReadinessPage },
  { meta: publicLandingMeta, rbac: publicLandingRbac, route: publicLandingRoute, Component: PublicLandingPage },
  { meta: publicStatusMeta, rbac: publicStatusRbac, route: publicStatusRoute, Component: PublicStatusPage },
  { meta: loginMeta, rbac: loginRbac, route: loginRoute, Component: LoginPage },
  { meta: accountSettingsMeta, rbac: accountSettingsRbac, route: accountSettingsRoute, Component: AccountSettingsPage },
  { meta: adminWarRoomMeta, rbac: adminWarRoomRbac, route: adminWarRoomRoute, Component: AdminWarRoomPage },
  { meta: aiBrainMeta, rbac: aiBrainRbac, route: aiBrainRoute, Component: AiBrainPage },
  { meta: aiPredictionsMeta, rbac: aiPredictionsRbac, route: aiPredictionsRoute, Component: AiPredictionsPage },
  { meta: binanceMeta, rbac: binanceRbac, route: binanceRoute, Component: BinancePage },
  { meta: alertsMeta, rbac: alertsRbac, route: alertsRoute, Component: AlertsPage },
  { meta: executiveStatusMeta, rbac: executiveStatusRbac, route: executiveStatusRoute, Component: ExecutiveStatusPage },
  { meta: historyMeta, rbac: historyRbac, route: historyRoute, Component: HistoryPage },
  { meta: ingestorsMeta, rbac: ingestorsRbac, route: ingestorsRoute, Component: IngestorsPage },
  { meta: orderbookRuntimeTruthMeta, rbac: orderbookRuntimeTruthRbac, route: orderbookRuntimeTruthRoute, Component: OrderbookRuntimeTruthPage },
  { meta: microstructureTrustMeta, rbac: microstructureTrustRbac, route: microstructureTrustRoute, Component: MicrostructureTrustPage },
  { meta: liquidationBridgeMeta, rbac: liquidationBridgeRbac, route: liquidationBridgeRoute, Component: LiquidationBridgePage },
  { meta: logsErrorsMeta, rbac: logsErrorsRbac, route: logsErrorsRoute, Component: LogsErrorsPage },
  { meta: marketMeta, rbac: marketRbac, route: marketRoute, Component: MarketPage },
  { meta: marketsIngestorsMeta, rbac: marketsIngestorsRbac, route: marketsIngestorsRoute, Component: MarketsIngestorsPage },
  { meta: marketsMeta, rbac: marketsRbac, route: marketsRoute, Component: MarketsPage },
  { meta: proChartMeta, rbac: proChartRbac, route: proChartRoute, Component: ProChartPage },
  { meta: publicLandingV2Meta, rbac: publicLandingV2Rbac, route: publicLandingV2Route, Component: PublicLandingV2Page },
  { meta: reportCenterMeta, rbac: reportCenterRbac, route: reportCenterRoute, Component: ReportCenterPage },
  { meta: strategyBacktestingMeta, rbac: strategyBacktestingRbac, route: strategyBacktestingRoute, Component: StrategyBacktestingPage },
  { meta: backtestsReplayMeta, rbac: backtestsReplayRbac, route: backtestsReplayRoute, Component: BacktestsReplayPage },
  { meta: technicalAnalysisMeta, rbac: technicalAnalysisRbac, route: technicalAnalysisRoute, Component: TechnicalAnalysisPage },
  { meta: traderMeta, rbac: traderRbac, route: traderRoute, Component: TraderPage },
  { meta: userStatusMeta, rbac: userStatusRbac, route: userStatusRoute, Component: UserStatusPage },
  { meta: marketBrainMeta, rbac: marketBrainRbac, route: marketBrainRoute, Component: MarketBrainPage },
];

export const PAGES: ReadonlyArray<PageModule> = RAW_PAGES.map(resolvePageModule);

export const ADMIN_PAGES: ReadonlyArray<PageModule> = PAGES.filter(
  (p) => p.meta.surface === 'admin' || p.meta.surface === 'system',
);
export const PUBLIC_PAGES: ReadonlyArray<PageModule> = PAGES.filter((p) => p.meta.surface === 'public');
export const APP_PAGES: ReadonlyArray<PageModule> = PAGES.filter((p) => p.meta.surface === 'app');
