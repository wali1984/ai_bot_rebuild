# Codex Design Handoff Review Policy

Status: `CODEX_DESIGN_HANDOFF_REVIEW_PROTOCOL_READY`

Codex must review any Claude Design handoff and any Claude Code implementation from that handoff before it can be marked ready.

Codex must challenge:

1. Whether design mock data is presented as real.
2. Whether static proof fixtures are labeled `STATIC_PROOF_FIXTURE`.
3. Whether read-only live market data is labeled `READONLY_MARKET_FEED`.
4. Whether missing data is shown as explicit evidence gap.
5. Whether any page remains placeholder-only.
6. Whether old/static/SVG chart remains primary when TradingView exists.
7. Whether TradingView/lightweight chart is the primary cockpit chart.
8. Whether every chart/panel shows data source and freshness.
9. Whether Mission Control is main cockpit.
10. Whether Operator Proof Dashboard remains evidence/proof page only.
11. Whether global `LIVE TRADING: BLOCKED_HUMAN_ONLY` remains visible.
12. Whether Admin AI cannot enable live trading or dangerous settings.
13. Whether Config Admin classifies settings as `safe_to_edit`, `requires_validation`, `requires_explicit_human_approval`, `read_only`, or `remove_or_replace`.
14. Whether dangerous settings require approval: live trading, live API keys, leverage increase, CROSS margin, max position increase, daily loss increase, kill switch disable, mandatory stop disable, hedge/DCA, `ADJUST_LEVERAGE`, and paper-to-live switch.
15. Whether Signal Explainability uses evidence and does not guess.
16. Whether Trainer Prediction Monitor shows `prediction_id`, `feature_snapshot_id`, `signal_id`, model/checkpoint, raw output, confidence, calibration, source freshness, top features, and missing-evidence warnings.
17. Whether Monitor Center shows all monitor scripts and trainer prediction stream.
18. Whether Script Registry is real and not placeholder.
19. Whether External / Manual Position Quarantine remains visible.
20. Whether mobile/iPhone readiness path is preserved.
21. Whether live/legacy/Redis/exchange mutation paths were added.
22. Whether the implementation updates required docs and payload requirements.

Codex must not treat Claude Design output as source of truth. V2 artifacts, runtime monitor payloads, read-only market/account payloads, audit ledger, risk decisions, trainer lineage, script registry, and GO/NO-GO markers remain source of truth.

The orchestrator remains distinct from the Risk Gateway. The orchestrator proposes, coordinates, enriches, and deconflicts. The Risk Gateway is final authority before execution.
