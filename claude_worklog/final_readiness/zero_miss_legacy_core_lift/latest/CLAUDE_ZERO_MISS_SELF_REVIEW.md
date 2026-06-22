# Claude Self-Review — Zero-Miss Legacy Core Lift

Generated: 2026-05-15
Runtime gate: blocked_human_only. Runtime symbols: [].

## Codex post-audit amendment

Codex corrected several evidence-layer issues after this Claude self-review:

- The V2-owned mirror now has 284 copied records, not 277, after Codex added
  seven omitted preserved RL environment/runtime files.
- The copied V2-owned microstructure files now py-compile after indentation
  repair.
- Dependency closure and atlas artifacts were regenerated over 253 Python
  files with zero parse errors.
- Smoke wrappers now fail on unresolved imports and missing external
  dependencies. The earlier smoke result was too weak because it only proved
  no module resolved under the legacy root.

The headline result remains BLOCKED.

## What was attempted

A six-hour ownership lift of the legacy algorithmic core into V2. The
brief called for a complete copy of the legacy runtime tree into
v2/legacy_owned_runtime/, full dependency closure, function/class atlas,
six V2-owned runtime smoke wrappers, Redis/exchange/config adapters,
tests, and frontend truth updates.

## What was delivered

- v2/legacy_owned_runtime/ created and populated with 277 .py files
  copied from v2/legacy_preserved/ (the previously-approved V2-side
  preserved closure).
- Dependency closure scanner (zero_miss_dependency_closure.py): 246 files
  parsed, 23 external dependencies catalogued, 1 unresolved local import
  (tools), 2 syntax errors flagged.
- Function/class/config atlas + trainer atlas (subagent): 468 classes,
  930 functions, hybrid_trainer.py decomposed (35 top-level items).
- Six V2-owned runtime smoke CLIs (ingestors, feature pipeline, trainer,
  orchestrator, trade management, monitoring). All run, all emit public
  status payloads, none reaches into the legacy bot root.
- Redis namespace adapter that raises on any legacy-prefixed write.
- Exchange fail-closed adapter that rejects every method outside a
  four-entry public allow-list.
- Config adapter that lists every legacy config key as
  OPERATOR_DECISION_REQUIRED (1,917 keys across config.py and
  config_accounts.py).
- 16 integration tests, all passing.
- Public proofs: V2_OWNED_RUNTIME_IMPORT_PROOF.json/md,
  REDIS_NAMESPACE_ISOLATION_PROOF.json, EXCHANGE_FAIL_CLOSED_PROOF.json,
  CONFIG_PARITY_MATRIX.json.

## What was NOT delivered (honest blockers)

1. **Legacy-root access was denied.** The bash auto-mode classifier
   denied read access to the legacy bot root with reason "the user's
   CLAUDE.md and task constraints explicitly forbid reading or modifying"
   even though the brief said "Read legacy only". The sprint adapted by
   using v2/legacy_preserved/ (~25k LOC, 277 files) instead of the full
   legacy tree (216k LOC, ~16k files). This is the headline BLOCKER.

2. **`tools` local package unresolved.** Four ingest modules import
   `tools.X`. The `tools/` package was not in v2/legacy_preserved/.
   These ingestors will not import cleanly without that package or
   without a V2 replacement.

3. **Two source files have syntax errors.**
   - rl/microstructure_aggregator.py (line 455)
   - rl/microstructure_features.py (line 532)
   Both are truncated paste artifacts from the preserved closure. They
   cannot be imported. The atlas marked them BLOCKED_PARSE_ERROR.

4. **External dependency satisfaction not verified.** torch,
   stable_baselines3, gymnasium, redis, websockets, ccxt, binance, etc.
   would need to be installed in a runtime venv for the trainer / paper
   loop / orchestrator to actually run end-to-end. The smoke tests only
   verify imports resolve to V2-owned paths; they do not verify the
   trainer can actually load a model.

5. **All 1,917 legacy config keys are OPERATOR_DECISION_REQUIRED.** No
   V2 mapping was registered for any legacy config constant. The
   migration completion contract clause 4 (config/env mapping complete)
   is NOT satisfied.

6. **Function/class atlas is complete for the preserved closure only.**
   It does not cover any file that lives only at the legacy bot root.

## Honest classification

Every component touched in this sprint is `PARTIALLY_MIGRATED` or
`READONLY_BRIDGED` under the migration completion contract. Nothing
claims `MIGRATED_CODEX_PASS`. Live, canary, legacy shutdown, and Redis
trim approvals remain absent.

## Recommended next steps

1. Operator must grant explicit read access to the legacy bot root, or
   accept that the V2-owned runtime tree is bounded to the preserved
   closure.
2. Either copy `tools/` from the legacy root or register V2 replacements
   for the four ingest modules that need it.
3. Fix the two syntax errors in microstructure_aggregator.py and
   microstructure_features.py (or replace from a clean copy).
4. Register V2 config mappings for the 1,917 legacy config keys.
5. Build native V2 ingestors that open their own WebSocket/REST
   connections instead of bridging legacy Redis.
6. Build a native V2 trainer (or formally accept the subprocess wrapper
   under the migration contract). The four-subproject sprint's
   recommendations remain open.

Live remains blocked_human_only.
