# ORCHESTRATOR_PROPOSAL_SIGNAL_FLOW_MAP — Phase F

File-level + stream-level map of the legacy orchestrator / proposal / signal flow.

## Flow

```text
trainer (rl/hybrid_trainer.py)
   │  writes
   ▼
trainer:predictions  (Redis stream)
   │  read by
   ▼
proposal stage (rl/orchestrator_worker.py + rl/proposal_hedge_preflight.py
                + rl/tradeplan_orchestrator.py + rl/decision_trace.py)
   │  writes
   ▼
wma:proposals  (Redis stream)
   │  read by
   ▼
orchestrator arbitration (rl/orchestrator_worker.py)
   │  (controlled by ORCHESTRATOR_WORKER_ENABLED + ORCHESTRATOR_WORKER_MODE
   │   read from config.py; consumer group "orchestrator_workers")
   ▼
signal publication
   ├─> canonical signal stream (legacy)
   ├─> primary-account signal stream
   └─> per-secondary-account signal stream
   │  consumed by
   ▼
traders (trading/trader.py, trading/trader-asjad.py)
   │  filtered by
   ▼
risk gates (risk/assertions.py, risk/halt_manager.py, risk/kill_switch.py, ...)
   │  passing through
   ▼
execution gates (trading/depth_execution_gate.py, fee_ratio_gate.py, ...)
   │
   ▼
exchange order placement (BLOCKED IN V2)
```

## Legacy files involved

### Orchestrator core

| file | role |
|---|---|
| `rl/orchestrator_worker.py` | orchestrator worker entry (`-m rl.orchestrator_worker [--shadow]`) |
| `rl/tradeplan_orchestrator.py` | trade-plan composition |
| `rl/decision_trace.py` | decision trace recording |
| `rl/proposal_hedge_preflight.py` | hedge preflight on proposals |

### Signal publication (legacy writes)

`utils/signal_publish.py`, `utils/signal_schema.py`, `trading/signal_router.py`, `trading/redis_stream_reader.py`

### Per-account routing

`config_accounts.py` — drives per-account streams; primary and Asjad account configs

### Coinank signal intake (trader-side consumption of CoinAnk)

`trading/coinank_signal_adapter.py`

### Shadow mode

Controlled via `config.py` `ORCHESTRATOR_WORKER_MODE = "shadow" | "live"`. The startup script branches on this:

```text
if mode == "shadow":
    python3 -m rl.orchestrator_worker --shadow
else:
    python3 -m rl.orchestrator_worker
```

## Signal record fields (inferred from utils/signal_schema.py and trading/coinank_signal_adapter.py)

The actual field set must be enumerated in the V2 orchestrator-adapter and V2 signal-publisher port's `LEGACY_BASELINE_ANALYSIS.md`. Anchor file paths for that work:

- `utils/signal_schema.py` — signal field set
- `utils/signal_publish.py` — publish entrypoint
- `trading/signal_router.py` — consumer-side parser
- `trading/coinank_signal_adapter.py` — CoinAnk-derived signal adaptor

## V2 mapping summary

| legacy artifact | V2 mapping | state |
|---|---|---|
| trainer:predictions writer | (none — V2 emits to V2-namespaced stream once trainer-bridge ships) | BLOCKED_BY_TRAINER_PARITY |
| wma:proposals consumer/producer | `v2_orchestrator_adapter_from_legacy_worker` (P1) | LEGACY_BASELINE_REQUIRED |
| canonical signal stream writer | `v2_signal_publisher` (P1) | LEGACY_BASELINE_REQUIRED |
| per-account signal streams | `v2_signal_publisher` + V2 config_admin_manager (per-account config) | LEGACY_BASELINE_REQUIRED |
| signal_schema fields | preserved in `utils/signal_schema.py`; V2 must use the same field set or document each change | mapping required |
| consumer group `orchestrator_workers` | not used by V2 (V2 uses its own stream namespace) | INTENTIONAL_CHANGE_WITH_REASON: V2 reads as reference, writes to v2:* |

## Required classification snapshot

- `ORCHESTRATOR_SOURCE_MAPPED` — yes
- `PROPOSAL_PIPELINE_MAPPED` — yes
- `SIGNAL_PUBLICATION_MAPPED` — yes (file-level)
- `SHADOW_MODE_BEHAVIOR_MAPPED` — yes
- `FUNCTION_LEVEL_FIELD_MAPPING_PENDING` — yes; V2 orchestrator-adapter port must extract field schema from `signal_schema.py` and document parity
- `V2_WRITER_NAMESPACE_INTENTIONAL_CHANGE` — V2 writes only `v2:*` streams; legacy stream names are read-only references
