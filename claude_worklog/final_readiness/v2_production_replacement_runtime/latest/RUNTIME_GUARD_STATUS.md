# V2 Production Replacement Runtime Guard Status

Generated: `2026-06-22T00:26:28Z`
Classification: `V2_PRODUCTION_REPLACEMENT_RUNTIME_DEGRADED`
Total v2:* keys: `1023123`

## Per-namespace counts

- `v2:market:*` -> 2688
- `v2:features:*` -> 27796
- `v2:prediction:*` -> 755
- `v2:orchestrator:*` -> 3
- `v2:signals:paper*` -> 757
- `v2:paper:*` -> 442
- `v2:risk:*` -> 7
- `v2:trainer:*` -> 786

## Per-phase results

- phase=`ingestors` returncode=1 stdout_tail=``
- phase=`features` returncode=1 stdout_tail=``
- phase=`rl_core` returncode=1 stdout_tail=``
- phase=`orchestrator` returncode=0 stdout_tail=`{"classification": "NO_OPEN_GATE_PROPOSALS_PAPER_ONLY", "proposals_arbitrated": 0, "bucket_winners_count": 0, "v2_orchestrator_keys_written_count": 3}`
- phase=`trade_mgmt` returncode=0 stdout_tail=`{"classification": "NO_PAPER_SIGNALS_PRESENT", "intents_built": 0, "intents_accepted": 0, "v2_paper_keys_written_count": 12}`

## Safety posture

- live_gate: blocked_human_only
- live_symbols: []
- approves_live: false
- approves_legacy_shutdown: false
- writes_legacy_redis: false
- places_exchange_orders: false
