import { lazy } from 'react';
import type { PageModule } from '../types/page';
import { resolvePageModule } from './productNavigation';

// ── Canonical admin pages (new consolidated IA) ──────────────────────────────
import adminOverviewMeta from './admin-overview/meta';
import adminOverviewRbac from './admin-overview/rbac';
import adminOverviewRoute from './admin-overview/route';

import adminDataMeta from './admin-data/meta';
import adminDataRbac from './admin-data/rbac';
import adminDataRoute from './admin-data/route';

import adminIntelligenceMeta from './admin-intelligence/meta';
import adminIntelligenceRbac from './admin-intelligence/rbac';
import adminIntelligenceRoute from './admin-intelligence/route';

import adminOrchestrationMeta from './admin-orchestration/meta';
import adminOrchestrationRbac from './admin-orchestration/rbac';
import adminOrchestrationRoute from './admin-orchestration/route';

import adminRiskMeta from './admin-risk/meta';
import adminRiskRbac from './admin-risk/rbac';
import adminRiskRoute from './admin-risk/route';

import adminExecutionMeta from './admin-execution/meta';
import adminExecutionRbac from './admin-execution/rbac';
import adminExecutionRoute from './admin-execution/route';

import adminExchangesMeta from './admin-exchanges/meta';
import adminExchangesRbac from './admin-exchanges/rbac';
import adminExchangesRoute from './admin-exchanges/route';

import adminConfigMeta from './admin-config/meta';
import adminConfigRbac from './admin-config/rbac';
import adminConfigRoute from './admin-config/route';

import adminUsersMeta from './admin-users/meta';
import adminUsersRbac from './admin-users/rbac';
import adminUsersRoute from './admin-users/route';

import adminReportsMeta from './admin-reports/meta';
import adminReportsRbac from './admin-reports/rbac';
import adminReportsRoute from './admin-reports/route';

import adminLogsMeta from './admin-logs/meta';
import adminLogsRbac from './admin-logs/rbac';
import adminLogsRoute from './admin-logs/route';

import adminAuditMeta from './admin-audit/meta';
import adminAuditRbac from './admin-audit/rbac';
import adminAuditRoute from './admin-audit/route';

import adminToolsMeta from './admin-tools/meta';
import adminToolsRbac from './admin-tools/rbac';
import adminToolsRoute from './admin-tools/route';

// ── Legacy pages (kept as redirect stubs / still registered at old paths) ────
import dashboardMeta from './dashboard/meta';
import dashboardRbac from './dashboard/rbac';
import dashboardRoute from './dashboard/route';

import missionControlMeta from './mission-control/meta';
import missionControlRbac from './mission-control/rbac';
import missionControlRoute from './mission-control/route';

import monitorCenterMeta from './monitor-center/meta';
import monitorCenterRbac from './monitor-center/rbac';
import monitorCenterRoute from './monitor-center/route';

import coverageSystemAtlasMeta from './coverage-system-atlas/meta';
import coverageSystemAtlasRbac from './coverage-system-atlas/rbac';
import coverageSystemAtlasRoute from './coverage-system-atlas/route';

import scriptRegistryMeta from './script-registry/meta';
import scriptRegistryRbac from './script-registry/rbac';
import scriptRegistryRoute from './script-registry/route';

import trainerPredictionMonitorMeta from './trainer-prediction-monitor/meta';
import trainerPredictionMonitorRbac from './trainer-prediction-monitor/rbac';
import trainerPredictionMonitorRoute from './trainer-prediction-monitor/route';

import signalExplainabilityMeta from './signal-explainability/meta';
import signalExplainabilityRbac from './signal-explainability/rbac';
import signalExplainabilityRoute from './signal-explainability/route';

import symbolsMeta from './symbols/meta';
import symbolsRbac from './symbols/rbac';
import symbolsRoute from './symbols/route';

import marketIntelligenceMeta from './market-intelligence/meta';
import marketIntelligenceRbac from './market-intelligence/rbac';
import marketIntelligenceRoute from './market-intelligence/route';

import signalsMeta from './signals/meta';
import signalsRbac from './signals/rbac';
import signalsRoute from './signals/route';

import executionsMeta from './executions/meta';
import executionsRbac from './executions/rbac';
import executionsRoute from './executions/route';

import positionsMeta from './positions/meta';
import positionsRbac from './positions/rbac';
import positionsRoute from './positions/route';

import riskMeta from './risk/meta';
import riskRbac from './risk/rbac';
import riskRoute from './risk/route';

import riskControlMeta from './risk-control/meta';
import riskControlRbac from './risk-control/rbac';
import riskControlRoute from './risk-control/route';

import exchangeManagerMeta from './exchange-manager/meta';
import exchangeManagerRbac from './exchange-manager/rbac';
import exchangeManagerRoute from './exchange-manager/route';

import externalManualPositionQuarantineMeta from './external-manual-position-quarantine/meta';
import externalManualPositionQuarantineRbac from './external-manual-position-quarantine/rbac';
import externalManualPositionQuarantineRoute from './external-manual-position-quarantine/route';

import configAdminMeta from './config-admin/meta';
import configAdminRbac from './config-admin/rbac';
import configAdminRoute from './config-admin/route';

import strategyAdminMeta from './strategy-admin/meta';
import strategyAdminRbac from './strategy-admin/rbac';
import strategyAdminRoute from './strategy-admin/route';

import trainerAdminMeta from './trainer-admin/meta';
import trainerAdminRbac from './trainer-admin/rbac';
import trainerAdminRoute from './trainer-admin/route';

import orchestratorAdminMeta from './orchestrator-admin/meta';
import orchestratorAdminRbac from './orchestrator-admin/rbac';
import orchestratorAdminRoute from './orchestrator-admin/route';

import executionAdminMeta from './execution-admin/meta';
import executionAdminRbac from './execution-admin/rbac';
import executionAdminRoute from './execution-admin/route';

import paperTradingMeta from './paper-trading/meta';
import paperTradingRbac from './paper-trading/rbac';
import paperTradingRoute from './paper-trading/route';

import replayMeta from './replay/meta';
import replayRbac from './replay/rbac';
import replayRoute from './replay/route';

import auditLedgerMeta from './audit-ledger/meta';
import auditLedgerRbac from './audit-ledger/rbac';
import auditLedgerRoute from './audit-ledger/route';

import systemHealthMeta from './system-health/meta';
import systemHealthRbac from './system-health/rbac';
import systemHealthRoute from './system-health/route';

import liveCanaryMeta from './live-canary/meta';
import liveCanaryRbac from './live-canary/rbac';
import liveCanaryRoute from './live-canary/route';

import liveReadinessMeta from './live-readiness/meta';
import liveReadinessRbac from './live-readiness/rbac';
import liveReadinessRoute from './live-readiness/route';

import claudeAdminAiMeta from './claude-admin-ai/meta';
import claudeAdminAiRbac from './claude-admin-ai/rbac';
import claudeAdminAiRoute from './claude-admin-ai/route';

import ollamaLocalAssistantMeta from './ollama-local-assistant/meta';
import ollamaLocalAssistantRbac from './ollama-local-assistant/rbac';
import ollamaLocalAssistantRoute from './ollama-local-assistant/route';

import codexReviewCenterMeta from './codex-review-center/meta';
import codexReviewCenterRbac from './codex-review-center/rbac';
import codexReviewCenterRoute from './codex-review-center/route';

import buildValidationStatusMeta from './build-validation-status/meta';
import buildValidationStatusRbac from './build-validation-status/rbac';
import buildValidationStatusRoute from './build-validation-status/route';

import operatorProofDashboardMeta from './operator-proof-dashboard/meta';
import operatorProofDashboardRbac from './operator-proof-dashboard/rbac';
import operatorProofDashboardRoute from './operator-proof-dashboard/route';

import mobileIphoneReadinessMeta from './mobile-iphone-readiness/meta';
import mobileIphoneReadinessRbac from './mobile-iphone-readiness/rbac';
import mobileIphoneReadinessRoute from './mobile-iphone-readiness/route';

import publicLandingMeta from './public-landing/meta';
import publicLandingRbac from './public-landing/rbac';
import publicLandingRoute from './public-landing/route';

import publicStatusMeta from './public-status/meta';
import publicStatusRbac from './public-status/rbac';
import publicStatusRoute from './public-status/route';

import loginMeta from './login/meta';
import loginRbac from './login/rbac';
import loginRoute from './login/route';

import permanentMigrationMeta from './permanent-migration/meta';
import permanentMigrationRbac from './permanent-migration/rbac';
import permanentMigrationRoute from './permanent-migration/route';

import accountSettingsMeta from './account-settings/meta';
import accountSettingsRbac from './account-settings/rbac';
import accountSettingsRoute from './account-settings/route';

import adminWarRoomMeta from './admin-war-room/meta';
import adminWarRoomRbac from './admin-war-room/rbac';
import adminWarRoomRoute from './admin-war-room/route';

import aiBrainMeta from './ai-brain/meta';
import aiBrainRbac from './ai-brain/rbac';
import aiBrainRoute from './ai-brain/route';

import aiPredictionsMeta from './ai-predictions/meta';
import aiPredictionsRbac from './ai-predictions/rbac';
import aiPredictionsRoute from './ai-predictions/route';

import binanceMeta from './binance/meta';
import binanceRbac from './binance/rbac';
import binanceRoute from './binance/route';

import alertsMeta from './alerts/meta';
import alertsRbac from './alerts/rbac';
import alertsRoute from './alerts/route';

import executiveStatusMeta from './executive-status/meta';
import executiveStatusRbac from './executive-status/rbac';
import executiveStatusRoute from './executive-status/route';

import historyMeta from './history/meta';
import historyRbac from './history/rbac';
import historyRoute from './history/route';

import ingestorsMeta from './ingestors/meta';
import ingestorsRbac from './ingestors/rbac';
import ingestorsRoute from './ingestors/route';

import orderbookRuntimeTruthMeta from './orderbook-runtime-truth/meta';
import orderbookRuntimeTruthRbac from './orderbook-runtime-truth/rbac';
import orderbookRuntimeTruthRoute from './orderbook-runtime-truth/route';

import microstructureTrustMeta from './microstructure-trust/meta';
import microstructureTrustRbac from './microstructure-trust/rbac';
import microstructureTrustRoute from './microstructure-trust/route';

import liquidationBridgeMeta from './liquidation-bridge/meta';
import liquidationBridgeRbac from './liquidation-bridge/rbac';
import liquidationBridgeRoute from './liquidation-bridge/route';

import logsErrorsMeta from './logs-errors/meta';
import logsErrorsRbac from './logs-errors/rbac';
import logsErrorsRoute from './logs-errors/route';

import marketMeta from './market/meta';
import marketRbac from './market/rbac';
import marketRoute from './market/route';

// market-root omitted: /market is handled by MERGED_LEGACY_PATHS → /markets

import marketsMeta from './markets/meta';
import marketsRbac from './markets/rbac';
import marketsRoute from './markets/route';

import marketsIngestorsMeta from './markets-ingestors/meta';
import marketsIngestorsRbac from './markets-ingestors/rbac';
import marketsIngestorsRoute from './markets-ingestors/route';

import proChartMeta from './pro-chart/meta';
import proChartRbac from './pro-chart/rbac';
import proChartRoute from './pro-chart/route';

import publicLandingV2Meta from './public-landing-v2/meta';
import publicLandingV2Rbac from './public-landing-v2/rbac';
import publicLandingV2Route from './public-landing-v2/route';

import reportCenterMeta from './report-center/meta';
import reportCenterRbac from './report-center/rbac';
import reportCenterRoute from './report-center/route';

import strategyBacktestingMeta from './strategy-backtesting/meta';
import strategyBacktestingRbac from './strategy-backtesting/rbac';
import strategyBacktestingRoute from './strategy-backtesting/route';

import backtestsReplayMeta from './backtests-replay/meta';
import backtestsReplayRbac from './backtests-replay/rbac';
import backtestsReplayRoute from './backtests-replay/route';

import technicalAnalysisMeta from './technical-analysis/meta';
import technicalAnalysisRbac from './technical-analysis/rbac';
import technicalAnalysisRoute from './technical-analysis/route';

import traderMeta from './trader/meta';
import traderRbac from './trader/rbac';
import traderRoute from './trader/route';

// trader-legacy omitted: /trader is handled by MERGED_LEGACY_PATHS → /trade

import userStatusMeta from './user-status/meta';
import userStatusRbac from './user-status/rbac';
import userStatusRoute from './user-status/route';

import marketBrainMeta from './market-brain/meta';
import marketBrainRbac from './market-brain/rbac';
import marketBrainRoute from './market-brain/route';

// config-admin-alias removed: /admin/config is owned by admin-config canonical page

const RAW_PAGES: ReadonlyArray<PageModule> = [
  // ── Canonical admin pages (10 primary + 3 secondary) ─────────────────────
  { meta: adminOverviewMeta, rbac: adminOverviewRbac, route: adminOverviewRoute, Component: lazy(() => import('./admin-overview')) },
  { meta: adminDataMeta, rbac: adminDataRbac, route: adminDataRoute, Component: lazy(() => import('./admin-data')) },
  { meta: adminIntelligenceMeta, rbac: adminIntelligenceRbac, route: adminIntelligenceRoute, Component: lazy(() => import('./admin-intelligence')) },
  { meta: adminOrchestrationMeta, rbac: adminOrchestrationRbac, route: adminOrchestrationRoute, Component: lazy(() => import('./admin-orchestration')) },
  { meta: adminRiskMeta, rbac: adminRiskRbac, route: adminRiskRoute, Component: lazy(() => import('./admin-risk')) },
  { meta: adminExecutionMeta, rbac: adminExecutionRbac, route: adminExecutionRoute, Component: lazy(() => import('./admin-execution')) },
  { meta: adminExchangesMeta, rbac: adminExchangesRbac, route: adminExchangesRoute, Component: lazy(() => import('./admin-exchanges')) },
  { meta: adminConfigMeta, rbac: adminConfigRbac, route: adminConfigRoute, Component: lazy(() => import('./admin-config')) },
  { meta: adminUsersMeta, rbac: adminUsersRbac, route: adminUsersRoute, Component: lazy(() => import('./admin-users')) },
  { meta: adminReportsMeta, rbac: adminReportsRbac, route: adminReportsRoute, Component: lazy(() => import('./admin-reports')) },
  { meta: adminLogsMeta, rbac: adminLogsRbac, route: adminLogsRoute, Component: lazy(() => import('./admin-logs')) },
  { meta: adminAuditMeta, rbac: adminAuditRbac, route: adminAuditRoute, Component: lazy(() => import('./admin-audit')) },
  { meta: adminToolsMeta, rbac: adminToolsRbac, route: adminToolsRoute, Component: lazy(() => import('./admin-tools')) },

  // ── Trader app pages ────────────────────────────────────────────────────────
  { meta: dashboardMeta, rbac: dashboardRbac, route: dashboardRoute, Component: lazy(() => import('./dashboard')) },
  { meta: permanentMigrationMeta, rbac: permanentMigrationRbac, route: permanentMigrationRoute, Component: lazy(() => import('./permanent-migration')) },
  { meta: missionControlMeta, rbac: missionControlRbac, route: missionControlRoute, Component: lazy(() => import('./mission-control')) },
  { meta: monitorCenterMeta, rbac: monitorCenterRbac, route: monitorCenterRoute, Component: lazy(() => import('./monitor-center')) },
  { meta: coverageSystemAtlasMeta, rbac: coverageSystemAtlasRbac, route: coverageSystemAtlasRoute, Component: lazy(() => import('./coverage-system-atlas')) },
  { meta: scriptRegistryMeta, rbac: scriptRegistryRbac, route: scriptRegistryRoute, Component: lazy(() => import('./script-registry')) },
  { meta: trainerPredictionMonitorMeta, rbac: trainerPredictionMonitorRbac, route: trainerPredictionMonitorRoute, Component: lazy(() => import('./trainer-prediction-monitor')) },
  { meta: signalExplainabilityMeta, rbac: signalExplainabilityRbac, route: signalExplainabilityRoute, Component: lazy(() => import('./signal-explainability')) },
  { meta: symbolsMeta, rbac: symbolsRbac, route: symbolsRoute, Component: lazy(() => import('./symbols')) },
  { meta: marketIntelligenceMeta, rbac: marketIntelligenceRbac, route: marketIntelligenceRoute, Component: lazy(() => import('./market-intelligence')) },
  { meta: signalsMeta, rbac: signalsRbac, route: signalsRoute, Component: lazy(() => import('./signals')) },
  { meta: executionsMeta, rbac: executionsRbac, route: executionsRoute, Component: lazy(() => import('./executions')) },
  { meta: positionsMeta, rbac: positionsRbac, route: positionsRoute, Component: lazy(() => import('./positions')) },
  { meta: riskMeta, rbac: riskRbac, route: riskRoute, Component: lazy(() => import('./risk')) },
  { meta: riskControlMeta, rbac: riskControlRbac, route: riskControlRoute, Component: lazy(() => import('./risk-control')) },
  { meta: exchangeManagerMeta, rbac: exchangeManagerRbac, route: exchangeManagerRoute, Component: lazy(() => import('./exchange-manager')) },
  { meta: externalManualPositionQuarantineMeta, rbac: externalManualPositionQuarantineRbac, route: externalManualPositionQuarantineRoute, Component: lazy(() => import('./external-manual-position-quarantine')) },
  { meta: configAdminMeta, rbac: configAdminRbac, route: configAdminRoute, Component: lazy(() => import('./config-admin')) },
  { meta: strategyAdminMeta, rbac: strategyAdminRbac, route: strategyAdminRoute, Component: lazy(() => import('./strategy-admin')) },
  { meta: trainerAdminMeta, rbac: trainerAdminRbac, route: trainerAdminRoute, Component: lazy(() => import('./trainer-admin')) },
  { meta: orchestratorAdminMeta, rbac: orchestratorAdminRbac, route: orchestratorAdminRoute, Component: lazy(() => import('./orchestrator-admin')) },
  { meta: executionAdminMeta, rbac: executionAdminRbac, route: executionAdminRoute, Component: lazy(() => import('./execution-admin')) },
  { meta: paperTradingMeta, rbac: paperTradingRbac, route: paperTradingRoute, Component: lazy(() => import('./paper-trading')) },
  { meta: replayMeta, rbac: replayRbac, route: replayRoute, Component: lazy(() => import('./replay')) },
  { meta: auditLedgerMeta, rbac: auditLedgerRbac, route: auditLedgerRoute, Component: lazy(() => import('./audit-ledger')) },
  { meta: systemHealthMeta, rbac: systemHealthRbac, route: systemHealthRoute, Component: lazy(() => import('./system-health')) },
  { meta: liveCanaryMeta, rbac: liveCanaryRbac, route: liveCanaryRoute, Component: lazy(() => import('./live-canary')) },
  { meta: liveReadinessMeta, rbac: liveReadinessRbac, route: liveReadinessRoute, Component: lazy(() => import('./live-readiness')) },
  { meta: claudeAdminAiMeta, rbac: claudeAdminAiRbac, route: claudeAdminAiRoute, Component: lazy(() => import('./claude-admin-ai')) },
  { meta: ollamaLocalAssistantMeta, rbac: ollamaLocalAssistantRbac, route: ollamaLocalAssistantRoute, Component: lazy(() => import('./ollama-local-assistant')) },
  { meta: codexReviewCenterMeta, rbac: codexReviewCenterRbac, route: codexReviewCenterRoute, Component: lazy(() => import('./codex-review-center')) },
  { meta: buildValidationStatusMeta, rbac: buildValidationStatusRbac, route: buildValidationStatusRoute, Component: lazy(() => import('./build-validation-status')) },
  { meta: operatorProofDashboardMeta, rbac: operatorProofDashboardRbac, route: operatorProofDashboardRoute, Component: lazy(() => import('./operator-proof-dashboard')) },
  { meta: mobileIphoneReadinessMeta, rbac: mobileIphoneReadinessRbac, route: mobileIphoneReadinessRoute, Component: lazy(() => import('./mobile-iphone-readiness')) },
  { meta: publicLandingMeta, rbac: publicLandingRbac, route: publicLandingRoute, Component: lazy(() => import('./public-landing')) },
  { meta: publicStatusMeta, rbac: publicStatusRbac, route: publicStatusRoute, Component: lazy(() => import('./public-status')) },
  { meta: loginMeta, rbac: loginRbac, route: loginRoute, Component: lazy(() => import('./login')) },
  { meta: accountSettingsMeta, rbac: accountSettingsRbac, route: accountSettingsRoute, Component: lazy(() => import('./account-settings')) },
  { meta: adminWarRoomMeta, rbac: adminWarRoomRbac, route: adminWarRoomRoute, Component: lazy(() => import('./admin-war-room')) },
  { meta: aiBrainMeta, rbac: aiBrainRbac, route: aiBrainRoute, Component: lazy(() => import('./ai-brain')) },
  { meta: aiPredictionsMeta, rbac: aiPredictionsRbac, route: aiPredictionsRoute, Component: lazy(() => import('./ai-predictions')) },
  { meta: binanceMeta, rbac: binanceRbac, route: binanceRoute, Component: lazy(() => import('./binance')) },
  { meta: alertsMeta, rbac: alertsRbac, route: alertsRoute, Component: lazy(() => import('./alerts')) },
  { meta: executiveStatusMeta, rbac: executiveStatusRbac, route: executiveStatusRoute, Component: lazy(() => import('./executive-status')) },
  { meta: historyMeta, rbac: historyRbac, route: historyRoute, Component: lazy(() => import('./history')) },
  { meta: ingestorsMeta, rbac: ingestorsRbac, route: ingestorsRoute, Component: lazy(() => import('./ingestors')) },
  { meta: orderbookRuntimeTruthMeta, rbac: orderbookRuntimeTruthRbac, route: orderbookRuntimeTruthRoute, Component: lazy(() => import('./orderbook-runtime-truth')) },
  { meta: microstructureTrustMeta, rbac: microstructureTrustRbac, route: microstructureTrustRoute, Component: lazy(() => import('./microstructure-trust')) },
  { meta: liquidationBridgeMeta, rbac: liquidationBridgeRbac, route: liquidationBridgeRoute, Component: lazy(() => import('./liquidation-bridge')) },
  { meta: logsErrorsMeta, rbac: logsErrorsRbac, route: logsErrorsRoute, Component: lazy(() => import('./logs-errors')) },
  { meta: marketMeta, rbac: marketRbac, route: marketRoute, Component: lazy(() => import('./market')) },
  { meta: marketsIngestorsMeta, rbac: marketsIngestorsRbac, route: marketsIngestorsRoute, Component: lazy(() => import('./markets-ingestors')) },
  { meta: marketsMeta, rbac: marketsRbac, route: marketsRoute, Component: lazy(() => import('./markets')) },
  { meta: proChartMeta, rbac: proChartRbac, route: proChartRoute, Component: lazy(() => import('./pro-chart')) },
  { meta: publicLandingV2Meta, rbac: publicLandingV2Rbac, route: publicLandingV2Route, Component: lazy(() => import('./public-landing-v2')) },
  { meta: reportCenterMeta, rbac: reportCenterRbac, route: reportCenterRoute, Component: lazy(() => import('./report-center')) },
  { meta: strategyBacktestingMeta, rbac: strategyBacktestingRbac, route: strategyBacktestingRoute, Component: lazy(() => import('./strategy-backtesting')) },
  { meta: backtestsReplayMeta, rbac: backtestsReplayRbac, route: backtestsReplayRoute, Component: lazy(() => import('./backtests-replay')) },
  { meta: technicalAnalysisMeta, rbac: technicalAnalysisRbac, route: technicalAnalysisRoute, Component: lazy(() => import('./technical-analysis')) },
  { meta: traderMeta, rbac: traderRbac, route: traderRoute, Component: lazy(() => import('./trader')) },
  { meta: userStatusMeta, rbac: userStatusRbac, route: userStatusRoute, Component: lazy(() => import('./user-status')) },
  { meta: marketBrainMeta, rbac: marketBrainRbac, route: marketBrainRoute, Component: lazy(() => import('./market-brain')) },
];

export const PAGES: ReadonlyArray<PageModule> = RAW_PAGES.map(resolvePageModule);

export const ADMIN_PAGES: ReadonlyArray<PageModule> = PAGES.filter(
  (p) => p.meta.surface === 'admin' || p.meta.surface === 'system',
);
export const PUBLIC_PAGES: ReadonlyArray<PageModule> = PAGES.filter((p) => p.meta.surface === 'public');
export const APP_PAGES: ReadonlyArray<PageModule> = PAGES.filter((p) => p.meta.surface === 'app');
