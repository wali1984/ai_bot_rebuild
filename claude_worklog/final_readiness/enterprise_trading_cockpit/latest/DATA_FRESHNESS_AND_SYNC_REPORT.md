# Data Freshness And Sync Report

Every cockpit payload row carries freshness metadata:

- `data_source`
- `generated_at`
- `last_event_at`
- `age_seconds`
- `freshness_state`
- `source_pointer`
- `evidence_link`
- `mode`

Static proof data is labeled `STATIC_PROOF_FIXTURE`. Exchange/account data gaps are
labeled `EVIDENCE_GAP`.

Static public payload:

- `v2/frontend/public/enterprise_trading_cockpit/latest/operator_cockpit_payload.json`

Source payload:

- `claude_worklog/final_readiness/enterprise_trading_cockpit/latest/operator_cockpit_payload.json`

Sync command:

```bash
cd v2/frontend
npm run sync:proof-artifacts
```

The sync command copies known `claude_worklog/final_readiness/*/latest`
packages into `v2/frontend/public/*/latest` so the cockpit can distinguish
source artifacts from public static copies. If a source artifact is newer than a
public copy, the cockpit payload must report a stale dashboard artifact warning.

DATA_FRESHNESS_AND_SYNC_REPORT_READY
