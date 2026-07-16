# Historical artifact classification

## Rule

Every root-level JSON, JSONL, inventory and generated graph in this directory
that predates the 2026-07-16 reconstruction is a **historical evidence snapshot**.
Its filename or a field such as `audit_complete`, `places_real_order`,
`trainer_status`, `passed`, `current`, `goal_locked` or `go` does not make it
current authority.

These artifacts were not silently rewritten because unknown scripts or dashboards
may depend on their schemas. A consumer must opt into the new atlas/current
documents and validate generation provenance explicitly.

## Classified historical machine artifacts

| Artifact | Historical meaning | Current authority/replacement |
|---|---|---|
| `GOAL_LOCK.json` | Earlier audit-goal coordination snapshot | Current Codex goal state and `REVERSE_ENGINEERING_INDEX.md`; never use this file as a runtime lock. |
| `PHASE_LEDGER.json` | Earlier audit-phase ledger | Current documentation index, command ledger and validation report. |
| `validation_results.json` | Earlier validation claims | `VALIDATION_AND_LIMITATIONS_2026-07-16.md` plus verbatim session evidence. |
| `live_gate_status.json` | Earlier live-gate summary | Effective process environment, `runtime_execution_state.py`, current risk register and runtime component. |
| `trainer_runtime_status.json` | Earlier trainer summary | Effective systemd/process state, current trainer component and fresh Redis/checkpoint evidence. |
| `operator_dashboard_payload.json` | Earlier derived dashboard payload | Primary producer/runtime state identified by the operator manual; never treat a cached dashboard as primary truth. |
| `file_inventory_backend.json` | Earlier backend inventory | `atlas/FILE_MODULE_CATALOG.json` and module index generated at the recorded commit. |
| `file_inventory_docs.json` | Earlier documentation inventory | Current Git tree and atlas file catalog. |
| `file_inventory_frontend.json` | Earlier frontend inventory | Current Git tree and TypeScript/JavaScript atlas. |
| `file_inventory_systemd.json` | Earlier unit inventory | Fresh effective `systemctl --user` plus installed fragments/drop-ins; repository inventory alone is insufficient. |
| `ingestor_inventory.json` | Earlier ingestor inventory | Current entrypoint/service registry plus effective runtime snapshot. |
| `redis_keyspace_map.json` | Earlier Redis map | Fresh safe Redis observation plus `atlas/REDIS_KEY_USAGE_REGISTRY.json`; neither alone is complete. |
| `gap_register.json` | Earlier gap list | `CURRENT_FINDINGS_AND_RISK_REGISTER.md`. |
| `ingestor_gap_register.json` | Earlier ingestor gaps | Current component documents and risk register. |
| `FINDINGS.jsonl` | Earlier individual findings | Current risk register; retain the JSONL only as provenance/history. |
| `data_flow_graph.mmd` | Earlier conceptual graph | Current master architecture plus runtime/data/trainer/execution component graphs. |
| `script_catalog.md` | Earlier script catalog | Current module index and entrypoint/service registry. |
| `unclassified_files.md` | Earlier classification exceptions | Current file/module catalog with explicit stratum and parse status. |

The older `*_MASTER_AUDIT.md`, `GO_NO_GO.md`, `CURRENT_GAPS_AND_BLOCKERS.md`,
`DATA_FLOW_MASTER_MAP.md`, `VALIDATION_SUMMARY.md` and
`SCRIPT_BY_SCRIPT_REFERENCE.md` files carry visible superseded banners and remain
historical supporting evidence.

## Consumer requirements

Before consuming any machine artifact as current:

1. require a schema version and generation timestamp;
2. bind it to a Git commit/content hash and dirty-tree state where applicable;
3. identify the primary source and whether this is a cache, projection or authority;
4. reject or visibly label stale data instead of refreshing `generated_at`;
5. validate source `event_time`, `ingested_at`, `available_at`,
   `feature_cutoff`, `decision_time` and `execution_time` independently;
6. compare installed runtime state when the artifact describes a process/unit;
7. never allow a historical `PASS`, `GO`, `ALLOW` or `audit_complete` field to
   enable live execution, promotion, deletion or deployment.

## Regeneration rule

The expanded current atlas JSON is deterministic and intentionally Git-ignored.
Regenerate it with the command in `REVERSE_ENGINEERING_INDEX.md`. Runtime status,
Redis counts, process lists, external routing and disk sizes must be recaptured
separately; the static generator cannot make those values current.
