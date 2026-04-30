# 18 Updated Pre-V2 Build Exit Criteria

## Consolidated enterprise exit criteria
All requirements below must be satisfied before architecture planning and V2 build implementation:

1. Existing baseline criteria from 01–09
- Observability, lineage, explainability, retention, heartbeat semantics, continuous monitoring, trainer internal worker supervision.

2. Enterprise website scope
- Website is the primary control center.
- Professional/polished UI requirement defined.
- No demo/sample pages in production scope.
- Operator vs admin boundary defined.

3. Dynamic symbol universe readiness
- GUI add/remove/update supported.
- Symbol states include train-enabled/trade-enabled/paper-only/live-disabled.
- Restart-free update model defined.

4. Hot-reload propagation readiness
- Universe updates propagate to ingestors, feature pipeline, trainer adapter, orchestrator, risk gateway, trader fleet, monitor, GUI.
- Versioned, audited, and rollback-capable update flow defined.

5. Multi-exchange connector readiness
- Connector interface includes all mandatory market/account/order methods.
- Live mutation methods explicitly blocked until gates pass.
- Binance Futures first, pluggable expansion path defined.

6. Multi-trader fleet readiness
- Fleet scaling model with mandatory trader fields defined.
- Risk Gateway final authority preserved.

7. Enterprise page map completeness
- Required page inventory present with purpose/data/controls/admin-only/safety/data-source mapping.

8. Public hosting and security readiness
- Auth, RBAC, HTTPS, reverse proxy, rate limits, audit logs, IP allowlist, 2FA-ready.
- No unauthenticated trading controls.
- Secrets never exposed to GUI.

9. 100x–1000x mission alignment with hard safety constraints
- Aggressive growth objective retained.
- Compounding, winrate, replay/paper, live-default-blocked, human-approval guardrails mandated.

## Architecture planning decision
Criteria status after adding requirements 10–17:
- Enterprise product scope: defined
- Safety and governance constraints: defined
- Data/control surface map: defined
- Hosting/security baseline: defined

ENTERPRISE_V2_REQUIREMENTS_READY_FOR_ARCHITECTURE
