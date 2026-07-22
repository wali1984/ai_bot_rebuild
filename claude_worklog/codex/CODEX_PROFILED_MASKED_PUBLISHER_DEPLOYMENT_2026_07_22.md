# Profiled masked-cost publisher deployment — 2026-07-22

## Outcome

The profiled base-feature publisher is enabled and active from pushed release
`c16fcd7aedfdbf3c37d1ec00fba308f698c7be71`. The complete protected Binance
commission credential bundle is absent, so the service selected
`MASKED_COST_OBSERVATION` mode. It did not reuse the existing Binance key whose
permission inspection showed trading and internal-transfer capability.

This restores continuous, causal 35-field parent publication without inventing
the four after-cost fields. It does **not** make those parents trainer-admissible
and does not activate optimization, checkpointing, prediction, paper, or live
authority.

## Immutable runtime binding

- release path:
  `/home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/c16fcd7aedfdbf3c37d1ec00fba308f698c7be71`
- release tracked diff against the same SHA: clean;
- remote branch head matched the release SHA before deployment;
- process CWD, `PYTHONPATH`, and `AI_BOT_CODE_SHA`: exact release SHA;
- dependency environment: existing read-only pinned deployment environment
  `6360ea33fcfb9f9a81724989bbd32ace2b02bf7eaa7a8771d64d282f423173f0`;
- effective `CREDENTIALS_DIRECTORY`: exact systemd per-unit path;
- exact per-unit credentials directory on the host: absent;
- service: active/running, enabled, `NRestarts=0`.

External deployment files updated:

- `/home/wali/.config/systemd/user/ai-bot-v2-profiled-base-feature-publisher.service`
- `/home/wali/.config/systemd/user/ai-bot-v2-profiled-base-feature-publisher.service.d/90-immutable-release.conf`

## Validation counts

- branch checkpoint selections: 86 passed, 0 failed;
- release-specific masked/deployment regression: 8 passed, 0 failed;
- Ruff violations: 0;
- Python compilation errors: 0;
- systemd scoped-unit verification errors: 0;
- credential names imported when present: 3 exact names;
- credentials present in the first deployed process: 0;
- cost or commission source calls in the first cycle: 0;
- fabricated cost values or receipts: 0;

The first deployed cycle reported:

- discovered symbols: 161;
- finalized-data-eligible symbols: 75;
- adaptively selected symbols: 1;
- inserted masked parents: 1;
- exact masked replays: 0;
- failed symbols: 0;
- explicit cost missing mask: `[1,1,1,1]`;
- explicit cost stale mask: `[0,0,0,0]`;
- explicit cost source-availability mask: `[0,0,0,0]`;
- legacy feature Redis writes: 0;
- market-performance thresholds applied: 0;
- publisher/trainer/prediction/paper/live authority grants: 0.

The resident trainer observer independently reopened the post-cycle ledger:

- integrity-verified records: 3;
- integrity-verified append receipts: 3;
- scan complete: true;
- strict training-eligible rows: 0;
- profiled 39-field child candidates: 0;
- trainer service process active: true;
- training loop active: false.

## Remaining admission gate

Masked publication is operational recovery, not a substitute for causal fees.
Trainer-admissible 35+4 children still require either:

1. a newly provisioned Binance key restricted to the signed commission-rate
   GET plus an independent fingerprint HMAC credential; or
2. a separately reviewed, authenticated causal commission-evidence producer.

After that source exists, activation requires a service restart and a **new**
finalized decision window. Historical masked parents are never retro-enriched.
