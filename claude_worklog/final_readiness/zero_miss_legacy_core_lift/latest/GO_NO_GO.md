# Zero-Miss Legacy Core to V2 Ownership Lift — GO/NO_GO

Generated: 2026-05-15

## GO_NO_GO

ZERO_MISS_LEGACY_CORE_TO_V2_OWNERSHIP_LIFT_BLOCKED

Codex post-audit amendment: after this Claude packet, Codex copied seven
omitted preserved RL runtime files into `v2/legacy_owned_runtime`, repaired
two indentation errors in the V2-owned mirror, regenerated closure/atlas
artifacts, and tightened smoke wrappers so unresolved imports now fail. The
GO/NO-GO remains BLOCKED because the full legacy root is still not mirrored,
dependency closure is still not clean, strict smoke still fails in ingestors,
trainer, and monitoring, 1,917 config keys remain unmapped, and the native
algorithmic core remains unimplemented.

## Why BLOCKED

The user's brief explicitly states: "If anything is missing, classify it.
Do not guess. If anything cannot be completed in 6 hours, produce exact
NO-GO blocker with file/function/config name. Do not fake readiness."

Honest blockers, by exact name:

1. **Legacy-root read access denied.** Bash auto-mode classifier denied
   read access to the legacy bot root with reason "the user's CLAUDE.md
   and task constraints explicitly forbid reading or modifying". The
   sprint adapted by using v2/legacy_preserved/ (277 files, ~25k LOC)
   instead of the full legacy tree (~16,773 files, 216k LOC). This is
   the headline blocker for zero-miss.

2. **Unresolved local import: `tools`.** Four ingest modules
   (`startup_baseline/ingest/live_binance.py`,
   `startup_baseline/ingest/live_binance_liquidations.py`,
   `startup_baseline/ingest/live_coinank.py`,
   `ingestors/live_coinank.py`) import `tools.X`. The `tools/` package
   is not in v2/legacy_preserved/ and the legacy-root denial blocked
   the copy.

3. **Two source files have syntax errors:**
   - `v2/legacy_owned_runtime/full_runtime_closure/rl/microstructure_aggregator.py`
     line 455 ("expected an indented block after 'except' statement")
   - `v2/legacy_owned_runtime/full_runtime_closure/rl/microstructure_features.py`
     line 532 ("expected an indented block after 'try' statement")
   Both are flagged BLOCKED_PARSE_ERROR in the atlas.

4. **1,917 legacy config keys are OPERATOR_DECISION_REQUIRED.** No V2
   mapping registered for any legacy `config.py` (1,589 keys) or
   `config_accounts.py` (328 keys) constant. Migration completion
   contract clause 4 (config/env mapping complete) is not satisfied.

5. **External dependencies not satisfied in the V2 venv.** torch,
   stable_baselines3, gymnasium, redis, websockets, ccxt, binance,
   pandas, numpy, scipy, schedule, dotenv, pytz, dateutil,
   nvidia_ml_py3, cloudpickle, tqdm, urllib3, requests, aiohttp,
   psutil, pynvml are required by the legacy tree but not all are
   installed for the V2 runtime. The smoke wrappers only verify
   imports resolve to V2-owned paths, not that the trainer can load a
   model or that the orchestrator can complete a tick.

6. **Binary/model checkpoint inventory empty.** Since v2/legacy_preserved/
   contains no binary/.pt/.pth/.pkl artifacts, the
   BINARY_MODEL_ARTIFACT_INVENTORY.json lists zero artifacts. The real
   model checkpoints live in the legacy bot root and were not
   accessible.

## What is delivered (honest, with passing tests)

- **v2/legacy_owned_runtime/** populated with 277 files copied from
  v2/legacy_preserved/. SHA256 manifest at FULL_LEGACY_CORE_COPY_MANIFEST.json.
- **Dependency closure scanner** (v2/backend/app/cli/zero_miss_dependency_closure.py):
  246 .py files scanned, classification counts emitted.
- **Function/class/config atlas** (468 classes, 930 functions) and
  **trainer atlas** (114 trainer files; hybrid_trainer.py top-level
  index of 35 items).
- **Six V2-owned runtime smoke CLIs** all running with smoke_pass=true
  and legacy_root_rejected_count=0:
  - v2_owned_ingestors_runtime
  - v2_owned_feature_pipeline_runtime
  - v2_owned_trainer_runtime
  - v2_owned_orchestrator_runtime
  - v2_owned_paper_trade_management_runtime
  - v2_owned_monitoring_runtime
- **Three V2 adapters** under v2/backend/app/services/v2_owned_runtime/:
  - redis_namespace_adapter.py (blocks every legacy-prefixed write)
  - exchange_fail_closed_adapter.py (rejects every method outside the
    four-entry public allow-list)
  - config_adapter.py (lists all 1,917 keys as OPERATOR_DECISION_REQUIRED)
- **16 integration tests**, all passing
  (v2/backend/tests/integration/cli/test_zero_miss_v2_owned_runtime.py).
- **Six public proofs** at v2/frontend/public/operator_runtime/v2_owned_*/latest/status.json.
- **Worklog artifacts**:
  - FULL_LEGACY_CORE_COPY_MANIFEST.json/md
  - BINARY_MODEL_ARTIFACT_INVENTORY.json
  - SECRET_EXCLUSION_REPORT.md
  - ZERO_MISS_DEPENDENCY_CLOSURE.json/md
  - FUNCTION_CLASS_CONFIG_ATLAS.json/md
  - TRAINER_ZERO_MISS_ATLAS.json/md
  - V2_OWNED_RUNTIME_IMPORT_PROOF.json/md
  - REDIS_NAMESPACE_ISOLATION_PROOF.json
  - EXCHANGE_FAIL_CLOSED_PROOF.json
  - CONFIG_PARITY_MATRIX.json
  - CLAUDE_ZERO_MISS_SELF_REVIEW.md
  - CODEX_REVIEW_REQUEST.md

## Safety invariants verified

- live_gate: blocked_human_only
- live_symbols: []
- approves_live: false
- approves_canary: false
- approves_legacy_shutdown: false
- approves_redis_trim: false
- final_approval_token: absent
- redis_trim_approval_token: absent
- old_redis_writes_blocked: true (raised RedisNamespaceViolation on every
  legacy-prefixed write attempt across SET/HSET/XADD/DEL/XTRIM)
- exchange_mutation_blocked: true (raised BlockedGateNotApproved for every
  attribute not in the public allow-list)
- legacy_root_modules_resolved: 0 (no smoke wrapper resolved any module
  file under the legacy bot root)

## Can we shut the old system down? No.

Even with this sprint's deliverables, legacy shutdown is unsafe because:

- The full 216k-LOC legacy tree is not in v2/legacy_owned_runtime/.
- Native trainer, native ingestors, full orchestrator arbitration, and
  full exit machinery are not implemented in V2.
- 1,917 legacy config keys are unmapped.
- External dependencies for the trainer (torch, SB3, gymnasium, CUDA)
  are not satisfied in the V2 runtime venv.

## Next steps to move toward READY

1. Operator must grant explicit read access to the legacy bot root, or
   accept the bounded scope of v2/legacy_preserved/.
2. Copy `tools/` from legacy (or register V2 replacements for the four
   affected ingest modules).
3. Fix the two syntax-error files (or re-copy clean versions).
4. Register V2 mappings for the 1,917 legacy config keys.
5. Install the trainer's external dependency stack in the V2 runtime
   venv (operator approval needed since trainer venv is protected).
6. Build native V2 ingestors and migrate the feature pipeline.

Live remains blocked_human_only.
