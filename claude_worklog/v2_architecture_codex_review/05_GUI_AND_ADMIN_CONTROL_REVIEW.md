# 05 GUI and Admin Control Review

## Scope
Verify GUI is full enterprise control plane and not a dashboard-only shell.

## Required pages check
Required pages are present in architecture, including:
- Mission Control
- Market Universe Manager
- Passive Market Discovery
- Adaptive Selection Engine
- Exchange Manager
- Ingestor Manager
- Feature Flow Map
- Feature Freshness Monitor
- Trainer Control Center
- Prediction Monitor
- Signal Explainability
- Confidence Driver Breakdown
- Orchestrator Control
- Risk Gateway
- Trader Fleet Manager
- Execution Monitor
- Positions/Portfolio
- Redis/Storage Health
- Continuous Monitor Dashboard
- Audit Ledger
- Config Admin
- Replay/Paper Trading
- Claude/Codex/Ollama Review Center
- AI Governance Console
- Live Readiness
- Deployment/Hosting Admin
- Mobile/iPhone Readiness

## Strengths
- Enterprise scope breadth is complete.
- Per-page purpose/data/control/admin/safety/source framing exists.
- Operator/admin separation intent is consistently stated.

## Adversarial gaps
1. **Role permission granularity not fully specified (HIGH)**
   - Pages identify admin-only controls, but no route-level or action-level permission matrix is defined.

2. **Safety-gate execution model is abstract (HIGH)**
   - Gates are named, but no deterministic precondition checklist contract per dangerous UI action.

3. **Data freshness UX contract not standardized (MEDIUM)**
   - Freshness visibility is required, but page-level stale/partial-data fallback behavior is not defined.

4. **No anti-drift contract between UI controls and backend policy schemas (MEDIUM)**
   - Architecture lacks a binding mechanism preventing UI from exposing controls not authorized by backend policy versions.

## Verdict
GUI control-plane scope is complete, but enforcement contracts are still too abstract for safe scaffold implementation.
