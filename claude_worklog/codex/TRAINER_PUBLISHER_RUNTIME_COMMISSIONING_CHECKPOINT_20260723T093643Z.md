# Trainer/Publisher Runtime Commissioning Checkpoint

Timestamp: `2026-07-23T09:36:43Z`

Branch: `codex/strategy-receipt-promotion-20260723`

Scope: bounded read-only verification of the four trainer/publisher units changed by merged recovery commit `6e250129`. No service, Redis, exchange, order, leverage, margin, strategy, or live-gate mutation was performed.

## Runtime evidence counts

- Merge-scoped units inspected: 4
- Service-manager records inspected: 8 (4 user + 4 system)
- User services running/down: `4 / 0`
- System-scope duplicates loaded: 0
- Units with `NRestarts=0`: `4 / 4`
- Units with `ExecMainStatus=0`: `4 / 4`
- Installed/staged unit hashes matching: `4 / 4`
- Bounded journal queries: 4
- Journal service records available: 0
- Redis output families mapped: 3
- Expected Redis keys: 153
- Redis fresh/present/stale/missing: `153 / 153 / 0 / 0`
- Service starts/stops/restarts/reloads: `0 / 0 / 0 / 0`
- Redis writes performed by this verification: 0
- Tests required/run: `0 / 0` (read-only runtime evidence and documentation only)
- Screenshots/routes/endpoints/builds required: `0 / 0 / 0 / 0`

## Service state

| Unit | State | Restarts | Active since | Immutable release |
| --- | --- | ---: | --- | --- |
| `ai-bot-v2-native-cuda-trainer-persistent.service` | active/running | 0 | 2026-07-22 23:19:38 EDT | `974caa6c263eeadf09fad5028d0883d304a14075` |
| `ai-bot-v2-profiled-base-feature-publisher.service` | active/running | 0 | 2026-07-22 23:18:02 EDT | `974caa6c263eeadf09fad5028d0883d304a14075` |
| `ai-bot-v2-profiled-training-observation-coordinator.service` | active/running | 0 | 2026-07-22 12:48:14 EDT | `37080a1cd015d5d51c0248f7b7e7fabbb9c24253` |
| `ai-bot-v2-binance-usdm-commission-evidence-broker.service` | active/running | 0 | 2026-07-22 03:16:00 EDT | `85f3ae173fe42e5af20d1bc9cb16effe3d1e85fc` |

The exact-schema feature producer and local trainer consumer are correctly aligned on release `974caa6c26`. No deployment drift repair or restart was required.

## Fresh producer result

The profiled feature publisher completed at `2026-07-23T09:29:05.960645Z`:

- classification: `CYCLE_COMPLETE_ALL_SELECTED_AUTHENTICATED_OR_UNCHANGED`
- selected/published/failed/deferred: `1 / 1 / 0 / 0`
- symbol: `ETHFIUSDT`
- elapsed: `62.845472001994494` seconds
- provenance preflights/rollovers: `1 / 1`
- status SHA-256: `97825d79c3899f1b338f02d3f9c052cafc08f6beed3a0c09289465fc33936b21`

This publisher intentionally writes the durable feature ledger, immutable CAS, state, and status files. It writes no feature Redis outputs and records `legacy_feature_redis_write_performed=false`.

## Fresh trainer result

The monitored optimizer cycle produced generation 46 at `2026-07-23T09:33:57.781820Z`:

- checkpoint: `v2_hybrid_ckpt_17cbe15f_0a23267c0ff27f50_6252e30f1cee`
- parent generation/checkpoint: `45 / v2_hybrid_ckpt_17cbe15f_3af042c8e3ba6873_e3edf3294a8f`
- CUDA/device/input dimension: `true / cuda:0 / 1784`
- manifest total/admitted/label-unavailable: `83 / 80 / 3`
- optimizer/validation/PIT-purged rows: `62 / 16 / 2`
- count invariants: `83 = 80 + 3`; `80 = 62 + 16 + 2`
- optimizer execution completed: true
- complete corpus reopened after optimizer: true
- full entry inventory verified: true
- full manifest authentication verified: true
- weight artifact bytes: `29,832,627`
- expected and independently recomputed weight SHA-256: `02708aa5a68ce4b847c46e39dd621c627f3a54b8734fafa4dbaba63dc66266ad`
- weight hash match: true

During the observed cycle, the trainer process remained active with approximately 92.7–92.8% CPU, 642 MiB CUDA process allocation, `NRestarts=0`, and no error status. A subsequent cycle began normally.

## Commission-evidence Redis contract

The broker is the only Redis producer among these four services:

```text
v2:binance_usdm:commission_evidence:mainnet:trader-wajidali1984:ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY:{symbol}
v2:binance_usdm:commission_evidence_version:mainnet:trader-wajidali1984:ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY:{symbol}
v2:binance_usdm:commission_rotation_claim:mainnet:trader-wajidali1984:ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY
```

For the exact 76-symbol broker universe: 76 authenticated evidence keys + 76 version keys + one claim key were present and fresh. Evidence TTLs ranged from `2,127,229` to `3,591,588` ms. No Redis `SCAN` was used.

## Honest authority boundary and remaining defects

The trainer/checkpoint publisher is online. Prediction serving is not online through this lane. The generation-46 artifact truthfully reports all of the following false:

- `runtime_wired`
- `deployment_authorized`
- `serving_activation_authorized`
- `prediction_authorized`
- `paper_trading_authorized`
- `live_execution_authorized`
- `order_submission_authorized`
- `exchange_access_authorized`

It is a locally authenticated, non-promotable research candidate. Its confidence calibration also remains unfitted with reason `NO_PIT_SAFE_EXPLICIT_COST_PROFITABILITY_TARGETS`. Neither boundary may be bypassed merely to make downstream status green.

The separately commissioned observation coordinator is healthy but deliberately parked at `HEAD_STAGED / WAITING_EXTERNAL_WITNESS_CONFIGURATION`; its older status timestamp is contractual because it writes once and waits. The external-witness path remains unconfigured and grants no downstream authority.

Recent journal-line validation remains unavailable because the host reported no journal files for all four bounded queries. Service state, immutable release identity, authenticated status files, candidate artifacts, exact Redis keys, and CAS advancement supplied the runtime evidence instead.

## Commands executed by the primary agent

```text
git diff --name-only 5ab3eda644 6e250129c9 | rg 'systemd|service|trainer|publisher|hybrid_cuda|native_cuda'
rg -n 'native_cuda_trainer|hybrid_cuda.*publish|publisher' [scoped service/source roots]
sed -n [scoped trainer/publisher/coordinator unit, drop-in, CLI, and checkpoint ranges]
git log --format=... [deployed release SHA to HEAD, three scoped component path sets]
rg --hidden -n 'ai_bot_local_data/deployments/ai_bot_rebuild|deployments/python_envs|ExecStartPre=/usr/bin/git -C' [scoped roots]
git show [deployed commits and operator-runbook changes]
git -C /home/wali/ai_bot_local_data/deployments/ai_bot_rebuild/974caa6c26... status --short
systemctl --user show ai-bot-v2-native-cuda-trainer-persistent.service [bounded properties]
ps -p 632947 [bounded process fields]
jq [bounded producer/trainer/candidate fields]
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader
find [local candidate directory, maxdepth 1, newest artifacts only]
sha256sum [generation-46 weight artifact]
```

Next safe family: trace and repair the authenticated candidate-inventory-to-PAPER-prediction path, including the missing PIT-safe explicit-cost profitability targets, without granting live execution or bypassing serving/promotion evidence.
