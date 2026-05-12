RUNTIME_TRUTH_SURFACE_REVIEW

Current truth shown by the cockpit:
- Live gate: `blocked_human_only`
- Supervisor: `SUPERVISOR_STATUS_STALE_OR_CONFLICTING`
- Master planner: not running in observed process/status evidence.
- Autonomous governor: not observed in current process/status evidence.
- Trainer runtime: `TRAINER_RUNTIME_EVIDENCE_MISSING`
- Legacy orchestrator: process observed read-only.
- Signal lineage: currently represented by `STATIC_PROOF_FIXTURE`, not live runtime truth.
- Payload freshness: stale payloads are explicitly counted.
- Redis trim: deferred/non-blocking.

No-guessing behavior:
- Trainer Prediction Monitor shows missing runtime evidence instead of fabricating prediction state.
- Signal Explainability keeps the explicit missing-evidence warning when evidence is absent.
- Static proof fixture lineage remains identified as non-live proof evidence.

Operator-visible correction:
- The first Mission Control viewport now shows the truth deck and runtime matrix before lower-level proof details.
- Monitor Center, Trainer Prediction Monitor, and Signal Explainability now include a route truth summary before their detailed tables/drawers.
