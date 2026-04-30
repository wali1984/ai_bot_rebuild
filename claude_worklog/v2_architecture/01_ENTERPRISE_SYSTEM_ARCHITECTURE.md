# 01 Enterprise System Architecture

## System definition
V2 is a local-first, enterprise-grade personal trading platform website with public-hosting-ready architecture.

## Core components
1. Web frontend (enterprise UI)
2. API backend (domain service layer)
3. Database (system-of-record for lineage, governance, audit)
4. Redis V2 namespace layer (`v2:*` only writes)
5. Monitor/evidence packet workers
6. Passive market discovery service
7. Adaptive symbol selection engine
8. Trainer adapter (initially read-only integration)
9. Orchestrator adapter
10. Risk gateway
11. Trader fleet manager
12. Replay/paper trading service
13. Audit ledger service
14. Claude/Codex/Ollama review center services
15. Public-hosting/security edge layer

## High-level data/control flow
Market + account feeds → discovery/observed universe → scoring/selection → universe versions/hot-reload → trainer/orchestrator adapters → risk gateway decisions → trader fleet intents/execution (paper-first) → monitoring/evidence/audit.

## Modes and safety posture
- Local-first default runtime.
- Public-hosting-ready with hardened ingress and RBAC.
- Live trading blocked by default.
- No V2 live execution until readiness gates pass.

## Deployment topology
- Single-node local dev + staged multi-service deployment model.
- Clear separation between read-only adapters and mutation-capable services.
- Risk Gateway and approval workflow are mandatory in mutation paths.

## Architecture constraints
- No demo/sample pages in production architecture.
- Every GUI page bound to real API/data sources.
- Legacy runtime remains untouched; V2 interacts through governed adapters.
