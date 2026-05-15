import type { PageModule } from '../types/page';

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

export const PAGES: ReadonlyArray<PageModule> = [
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
];

export const ADMIN_PAGES: ReadonlyArray<PageModule> = PAGES.filter((p) => p.meta.surface === 'admin');
export const PUBLIC_PAGES: ReadonlyArray<PageModule> = PAGES.filter((p) => p.meta.surface === 'public');
